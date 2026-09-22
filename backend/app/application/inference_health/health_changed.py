"""`voice:health` announcement → `INFERENCE_HEALTH_CHANGED` on every ACTIVE session (§4.3).

See the package docstring for the invariant this module is built around. The whole use case is
one read of the ACTIVE session ids and one event append per session, in one Unit of Work of its
own.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.simulation.sim_time import running_ms
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType, HealthStatus, SessionState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["AppendInferenceHealthChanged", "HealthTransition"]

logger = logging.getLogger(__name__)


class HealthTransition(BaseModel):
    """One `voice:health` message — `{service, from, to, detail, at}` (§4.3, literally).

    `from` is a Python keyword, so the field is `previous` with the wire name as its alias; the
    alias is what parsing and serialising both use, so the contract on the bus is unchanged.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    service: str
    previous: HealthStatus = Field(alias="from")
    new: HealthStatus = Field(alias="to")
    detail: str | None = None
    at: str | None = None


class AppendInferenceHealthChanged:
    """Append one `INFERENCE_HEALTH_CHANGED` per ACTIVE session (§10.13, actor `SYSTEM`).

    Returns the sessions it appended to, which is what its tests assert on and what the caller
    logs. A message that does not parse, or names a state that is not a `HealthStatus`, returns
    an empty list after a warning: see the package docstring for why that is a drop and not a
    raise.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def from_message(self, raw: str | bytes) -> list[SessionId]:
        """Parse one pub/sub message and apply it; a malformed one is logged and dropped."""
        try:
            transition = HealthTransition.model_validate_json(raw)
        except ValidationError:
            logger.warning("dropping a malformed voice:health message")
            return []
        return await self(transition)

    async def __call__(self, transition: HealthTransition) -> list[SessionId]:
        """Append the event to every ACTIVE session; no ACTIVE session means no write."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            session_ids = await uow.sessions.list_active_session_ids()
            if not session_ids:
                # Nothing to append to. The Unit of Work is left without a commit, which rolls
                # back a transaction that wrote nothing and publishes nothing (D5).
                return []
            appended: list[SessionId] = []
            for session_id in session_ids:
                session = await uow.sessions.get(session_id)
                if session is None or session.state is not SessionState.ACTIVE:
                    # Raced with a completion between the id read and the row read; the log of a
                    # session that is no longer ACTIVE is closed (D9).
                    continue
                await uow.events.append(
                    session_id, _events(transition, offset_ms=running_ms(session, now))
                )
                appended.append(session_id)
            await uow.commit()
        return appended


def _events(transition: HealthTransition, *, offset_ms: int) -> Sequence[DomainEvent]:
    """The one event, with §10.13's payload keys literally."""
    return [
        DomainEvent(
            event_type=EventType.INFERENCE_HEALTH_CHANGED,
            actor=ActorRef(actor_type=ActorType.SYSTEM),
            monotonic_offset_ms=offset_ms,
            payload={
                "component": transition.service,
                "previous_status": transition.previous.value,
                "new_status": transition.new.value,
                "detail": transition.detail or "",
            },
        )
    ]
