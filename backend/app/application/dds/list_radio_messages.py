"""`listRadioMessages` — the radio log (`openapi.yaml`, §20.1).

*"Radio messages have **no table**: they are read from `session_events`
(`RADIO_MESSAGE_CREATED`) through a read model built from the log. Filtered to `to_role == the
caller's role`."* That is the whole design, and it is why this module holds no repository beyond
the event store: a radio message is an event, and materializing it a second time would create a
projection that could disagree with the audit source (D5, SPEC §8).

Paging is `after_seq_no` + `limit`, and `last_seq_no` comes back as the cursor for the next call —
the same shape `listSessionEvents` and the WebSocket `resume` use, so a console polls the radio
log exactly as it resumes the stream (§40.3).

The role filter is the caller's *simulation* role, as with `listNotifications`; an instructor sees
every `to_role`, which is the console's job (SPEC §7).
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.list_notifications import audience_roles_for
from app.application.dds.views import RadioMessagePage, RadioMessageView, radio_message_views
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId

__all__ = ["ListRadioMessages"]


class ListRadioMessages:
    """`listRadioMessages` (`openapi.yaml`): the log's `RADIO_MESSAGE_CREATED` rows, projected."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        after_seq_no: int = 0,
        limit: int = 100,
    ) -> RadioMessagePage:
        """Radio traffic addressed to the caller's role, in log order."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            roles = audience_roles_for(session, user) if can_observe(session, user) else ()
            if not roles:
                raise ForbiddenForRoleError(
                    f"the caller may not read the radio log of session {session_id}"
                )
            events = await uow.events.read(session_id, after_seq_no=after_seq_no)
            await uow.commit()

        incident_id = UUID(str(session.incident.incident_id))
        items: list[RadioMessageView] = []
        last_seq_no = after_seq_no
        for role in roles:
            page = radio_message_views(
                events,
                incident_id=incident_id,
                to_role=role,
                after_seq_no=after_seq_no,
                limit=limit,
            )
            items.extend(page.items)
        items.sort(key=lambda item: item.seq_no)
        del items[limit:]
        if items:
            last_seq_no = items[-1].seq_no
        return RadioMessagePage(items=tuple(items), last_seq_no=last_seq_no)
