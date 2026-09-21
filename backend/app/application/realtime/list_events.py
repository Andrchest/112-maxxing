"""`listSessionEvents` — the REST twin of the WebSocket replay (`openapi.yaml`, §40.2, §40.4).

`openapi.yaml`: "The REST twin of the WebSocket replay: the same envelopes, the same per-role
filtering by `DataVisibilityPolicy.may_receive` and the same payload redaction table". "Same" is
literal here: this use case calls `app.application.realtime.redaction.redact` — the one function —
and returns `RealtimeEnvelope`s, which is the very type the socket's `event` frame is built from.
`backend/tests/api/realtime/test_events_endpoint.py` asserts the two JSON objects are equal for
the same rows and role, so the claim is checked rather than merely written down.

Paging semantics, from the contract:

* `after_seq_no` is exclusive and may be `0`;
* `limit` bounds the number of **visible** items returned, not the number of rows read — a
  trainee's page must not shrink because the instructor-only events between two of their own fell
  in the same window. Rows are therefore read in chunks until the page is full or the log ends;
* `last_seq_no` is the highest `seq_no` **visible to the caller's role** in the whole log, the
  same definition `SessionDetail.last_seq_no` carries, so either can be used as a resume cursor;
* `has_more` is true when the scan stopped because the page filled, not because the log ended.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.realtime.effective_role import Connection, connection_of, fold_role
from app.application.realtime.redaction import (
    RealtimeEnvelope,
    redact,
    source_of_row,
    visible_event_types,
)
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

__all__ = ["ListSessionEvents", "SessionEventPageView", "role_last_seq_no"]

#: How many raw rows one read pulls while filling a page of visible items. A page of 200 visible
#: events rarely needs more than one of these, and each round trip is an index scan on
#: `ix_session_events_session_seq`.
_READ_CHUNK_MULTIPLIER = 4


@dataclass(frozen=True)
class SessionEventPageView:
    """`openapi.yaml`'s `SessionEventPage` as application data."""

    items: tuple[RealtimeEnvelope, ...]
    last_seq_no: int
    has_more: bool


async def role_last_seq_no(uow: UnitOfWork, session_id: SessionId, connection: Connection) -> int:
    """The highest `seq_no` visible to a connection's role, inside an open Unit of Work.

    This is what `SessionDetail.last_seq_no` is documented as ("the highest `seq_no` **visible to
    the caller's role**") and what `app.application.sessions.queries` uses for that field.
    It is deliberately the *type-level* answer: §40.4's three per-payload delivery filters
    (`STAGE_STATE_CHANGED.role_type` and the notification/radio audiences) can only make the real
    cursor lower, which costs a client a replayed event it then discards — never a hidden one.
    """
    return await uow.events.last_seq_no(
        session_id, event_types=visible_event_types(connection.role)
    )


def connection_for_read(session: SimulationSession, viewer: AuthenticatedUser) -> Connection:
    """The caller's §40.1 connection, or `403` — the same derivation the WebSocket uses.

    `openapi.yaml` gives `listSessionEvents` the same `403` as `getSession`, and a non-participant
    trainee has no effective role at all, so there is nothing to filter *by*.
    """
    try:
        return connection_of(session, viewer)
    except ParticipantNotAssignedError as error:
        raise ForbiddenForRoleError(
            f"the caller may not read the event log of session {session.id}"
        ) from error


class ListSessionEvents:
    """`listSessionEvents` — one page of role-filtered envelopes (`openapi.yaml`, D8)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        session_id: SessionId,
        *,
        viewer: AuthenticatedUser,
        after_seq_no: int = 0,
        limit: int = 200,
        event_types: Collection[EventType] | None = None,
    ) -> SessionEventPageView:
        """The page; raises `SessionNotFoundError` (`404`) or `ForbiddenForRoleError` (`403`).

        `event_types` is `openapi.yaml`'s optional filter — "still intersected with the role's
        visible set", which it is, because it is applied *after* `redact` has had its say.
        """
        wanted = frozenset(event_types) if event_types else None
        chunk = max(limit * _READ_CHUNK_MULTIPLIER, limit)

        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            connection = connection_for_read(session, viewer)

            items: list[RealtimeEnvelope] = []
            cursor = after_seq_no
            has_more = False
            while not has_more:
                rows = await uow.events.read(session_id, cursor, chunk)
                if not rows:
                    break
                exhausted = len(rows) < chunk
                for row in rows:
                    cursor = row.seq_no
                    envelope = redact(source_of_row(row), connection.role, connection.policy)
                    connection = fold_role(connection, row.event_type, row.payload)
                    if envelope is None or (wanted is not None and row.event_type not in wanted):
                        continue
                    if len(items) == limit:
                        has_more = True
                        break
                    items.append(envelope)
                if exhausted:
                    break

            last_seq_no = await role_last_seq_no(uow, session_id, connection)
            await uow.commit()

        return SessionEventPageView(items=tuple(items), last_seq_no=last_seq_no, has_more=has_more)
