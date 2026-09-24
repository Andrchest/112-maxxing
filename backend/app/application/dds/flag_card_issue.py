"""`flagDdsCardIssue` — «Отметить ошибку в карточке»: the ДДС flags an error in the received card
(I3 E5b, HLD 70 §70.2.4, §70.4.4, §70.7; C1, D19).

Only under `dds_card_check: ON`: the customer's latest answer (23.09, REQ-5915) is that the ДДС
does not check the 112 card, so the switch defaults `OFF`; the 18.09 reading (msg638) — the ДДС
checks the card's correctness — is the `ON` variant, in both `dds_mode`s (§70.11): memo
`ACKNOWLEDGED`, and every picker state from `ACKNOWLEDGED` until the stage closes. With `OFF` no
action table offers `flag_card_issue`, so the gate answers `409 ACTION_NOT_AVAILABLE`.

One command, in the fixed order below:

1. `DdsCommandGate.open` with `x-action` `flag_card_issue` (card check `ON`, the card held);
2. the leg must be one of this stage's (`404`) and the caller must play it (`403
   FORBIDDEN_FOR_SERVICE`, §70.4.5) — the flag is raised by the service that received the card;
3. `comment_ru` must not be blank (`422 COMMENT_REQUIRED`); a `field_path`, when given, must be a
   path of the session's card schema (`422 CARD_FIELD_UNKNOWN`);
4. one `DDS_CARD_ISSUE_FLAGGED` (TRAINEE) is appended; nothing else moves.

**INV 3.** The flag is recorded against the frozen snapshot only: this module reads the legs and the
card schema of the pack the session recorded, never world truth and never the scenario. Whether the
flag was *right* is scoring's question (`applies_to_variants: {dds_card_check: [ON]}` rules over
`(ScenarioVersion, events)`), never this command's.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandContext, DdsCommandGate
from app.application.dds.set_service_status import check_leg_bound
from app.application.dds.views import CardIssueKind, CardIssueView
from app.domain.common.errors import DomainError
from app.domain.common.ids import AssignmentId, SessionId
from app.domain.events.catalog import validate_payload
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = [
    "ACTION_ID",
    "CardIssueCommentRequiredError",
    "CardIssueFieldUnknownError",
    "FlagDdsCardIssue",
]

ACTION_ID = "flag_card_issue"
"""`openapi.yaml`'s `x-action` for `flagDdsCardIssue`."""


class CardIssueCommentRequiredError(DomainError):
    """A card issue without a (non-blank) comment (`422 COMMENT_REQUIRED`)."""

    code = "COMMENT_REQUIRED"

    def __init__(self) -> None:
        super().__init__("a card issue requires a non-blank comment_ru")


class CardIssueFieldUnknownError(DomainError):
    """The flagged `field_path` is not a path of the session's card schema (`422`)."""

    code = "CARD_FIELD_UNKNOWN"

    def __init__(self, field_path: str) -> None:
        self.field_path = field_path
        super().__init__(f"field_path {field_path!r} is not a field of the session's card schema")


class FlagDdsCardIssue:
    """`flagDdsCardIssue` (`openapi.yaml`): one `DDS_CARD_ISSUE_FLAGGED`."""

    def __init__(self, gate: DdsCommandGate) -> None:
        self._gate = gate

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        assignment_id: AssignmentId,
        issue_kind: CardIssueKind,
        comment_ru: str,
        field_path: str | None = None,
    ) -> CardIssueView:
        """Record the flag (see the module docstring for the order of the checks)."""
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            leg = ctx.leg(assignment_id)
            check_leg_bound(leg, user.user_id)
            if not comment_ru.strip():
                raise CardIssueCommentRequiredError()
            if field_path is not None and field_path not in ctx.card_schema:
                raise CardIssueFieldUnknownError(field_path)
            stored = await ctx.append(
                [_flagged(ctx, assignment_id, issue_kind, comment_ru, field_path)]
            )
            return CardIssueView(
                event_id=UUID(str(stored[0].id)),
                assignment_id=UUID(str(assignment_id)),
                field_path=field_path,
                issue_kind=issue_kind,
                comment_ru=comment_ru,
                at_offset_ms=ctx.now_ms,
            )


def _flagged(
    ctx: DdsCommandContext,
    assignment_id: AssignmentId,
    issue_kind: CardIssueKind,
    comment_ru: str,
    field_path: str | None,
) -> DomainEvent:
    """`DDS_CARD_ISSUE_FLAGGED` (TRAINEE, HLD 70 §70.7)."""
    payload = {
        "assignment_id": UUID(str(assignment_id)),
        "field_path": field_path,
        "issue_kind": issue_kind.value,
        "comment_ru": comment_ru,
        "actor_user_id": UUID(str(ctx.actor.actor_id)),
        "at_offset_ms": ctx.now_ms,
    }
    validate_payload(EventType.DDS_CARD_ISSUE_FLAGGED, payload)
    return DomainEvent(
        event_type=EventType.DDS_CARD_ISSUE_FLAGGED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload=payload,
    )
