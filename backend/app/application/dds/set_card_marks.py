"""`setDdsCardMarks` — the ДДС screen's «ЧС» / «ЧП» marks with the pencil (I7 E55; owner decision
2026-09-29, Q9; `СКРИНШОТ ДДСГСИ.docx` image6, REQ-3040).

The marks are the ДДС's own, not the 112 card's: any ДДС participant of a memo-mode session sets
them (default both off), they are shown read-only to the instructor and in the report, and no
scoring evaluator reads them. One command, in the fixed order below:

1. `DdsCommandGate.open` with any of `set_service_status` / `close` — the actions a memo stage
   offers for as long as the ДДС still holds the card (`RECEIVED` … `RESOLVED`; nothing once it is
   `CLOSED`). No row of its own in the §10.9 / §70.4.4 action tables: the marks are not a step of
   the stage machine, so they ride on the rows that already say "the card is open";
2. memo mode only — a picker session ⇒ `409 ACTION_NOT_AVAILABLE` (the picker screen has no marks);
3. the marks the log holds (`dds_marks_of`) are compared with the request: a change appends one
   `DDS_CARD_MARKS_SET` (TRAINEE), an unchanged pair appends nothing (idempotent); the audit row's
   «было → стало» carries `dds_card.chs` / `dds_card.chp` (I7 E43).

Answers with the work item as it now stands (its `dds_marks` included).
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    ActionNotAvailableError,
    DdsCommandContext,
    DdsCommandGate,
    is_memo,
)
from app.application.handoff.work_item import DdsMarksView, DdsWorkItemView, dds_marks_of
from app.application.ports.audit_changes import NO_AUDIT_CHANGES, AuditChangeCollector
from app.domain.common.ids import SessionId
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "GATE_ACTION_IDS", "SetDdsCardMarks"]

ACTION_ID = "set_card_marks"
"""The name a `409 ACTION_NOT_AVAILABLE` reports for this command."""

GATE_ACTION_IDS: tuple[str, ...] = ("set_service_status", "close")
"""The memo actions whose presence means the ДДС still holds the card (see the module docstring)."""


class SetDdsCardMarks:
    """`setDdsCardMarks` (`openapi.yaml`): at most one `DDS_CARD_MARKS_SET`."""

    def __init__(
        self, gate: DdsCommandGate, *, changes: AuditChangeCollector = NO_AUDIT_CHANGES
    ) -> None:
        self._gate = gate
        self._changes = changes

    async def __call__(
        self, session_id: SessionId, user: AuthenticatedUser, *, chs: bool, chp: bool
    ) -> DdsWorkItemView:
        """Set the marks (see the module docstring for the order of the checks)."""
        async with self._gate.open(session_id, user, GATE_ACTION_IDS) as ctx:
            if not is_memo(ctx.session):
                raise ActionNotAvailableError(ACTION_ID, ctx.stage_state)
            before = dds_marks_of(ctx.full_log)
            after = DdsMarksView(chs=chs, chp=chp)
            if after != before:
                await ctx.append([_marks_set(ctx, before, after)])
            self._changes.record("dds_card", "chs", before.chs, after.chs)
            self._changes.record("dds_card", "chp", before.chp, after.chp)
            return ctx.work_item()


def _marks_set(ctx: DdsCommandContext, before: DdsMarksView, after: DdsMarksView) -> DomainEvent:
    """`DDS_CARD_MARKS_SET` (TRAINEE, I7 E55)."""
    payload = {
        "previous_chs": before.chs,
        "previous_chp": before.chp,
        "chs": after.chs,
        "chp": after.chp,
        "actor_user_id": UUID(str(ctx.actor.actor_id)),
        "at_offset_ms": ctx.now_ms,
    }
    validate_payload(EventType.DDS_CARD_MARKS_SET, payload)
    return DomainEvent(
        event_type=EventType.DDS_CARD_MARKS_SET,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload=payload,
    )
