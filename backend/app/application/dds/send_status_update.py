"""`sendDdsStatusUpdate` — report progress on the incident (`openapi.yaml`, §10.9).

**Not a stage transition.** `send_status_update` is an `ActionDescriptor` with `trigger = None`:
it is available in every state from `ACKNOWLEDGED` to `RESOLVED` and moves nothing. What it
produces is one `DDS_STATUS_UPDATE_SENT` event — `x-emits` lists that and nothing else — which is
what the `REQUIRED_STATUS_UPDATE` evaluator reads (§10.14, E15).

There is no `status_updates` table: §20.5 declares none, and the event log is the record (D5). The
`StatusUpdateView` the endpoint answers with is therefore built from what was just appended, not
read back from anywhere.

`assignment_id` is the primary leg's, for the same reason every other trainee event carries it:
one action, one event (E9 analyst R5). `text_ru` is the trainee's own words and is stored
verbatim; the length bound is the contract's (`1..2000`) and is enforced by the request schema.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandGate
from app.application.dds.views import StatusUpdateView
from app.domain.common.ids import SessionId
from app.domain.enums import StatusUpdateKind
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "SendDdsStatusUpdate"]

ACTION_ID = "send_status_update"
"""`openapi.yaml`'s `x-action` for `sendDdsStatusUpdate`."""


class SendDdsStatusUpdate:
    """`sendDdsStatusUpdate` (`openapi.yaml`): one incident status update, one event."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        update_kind: StatusUpdateKind,
        text_ru: str,
    ) -> StatusUpdateView:
        """Append `DDS_STATUS_UPDATE_SENT`; the stage does not move."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            assignment_id = UUID(str(ctx.primary.assignment_id))
            actor_user_id = UUID(str(ctx.actor.actor_id))
            await ctx.append(
                [
                    DomainEvent(
                        event_type=EventType.DDS_STATUS_UPDATE_SENT,
                        actor=ctx.actor,
                        monotonic_offset_ms=ctx.now_ms,
                        payload={
                            "assignment_id": assignment_id,
                            "update_kind": update_kind.value,
                            "text_ru": text_ru,
                            "at_offset_ms": ctx.now_ms,
                            "actor_user_id": actor_user_id,
                        },
                    )
                ]
            )
            return StatusUpdateView(
                assignment_id=assignment_id,
                update_kind=update_kind,
                text_ru=text_ru,
                at_offset_ms=ctx.now_ms,
                actor_user_id=actor_user_id,
            )
