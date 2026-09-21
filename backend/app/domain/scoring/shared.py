"""Helpers two or more evaluators need, kept in one place (HLD `10-domain-model.md` §10.14).

Two of the ten evaluators pick their evidence the same way ("the card revision the value came
from, else the handoff, else the bounding stage event") and three of them match an event payload
against a `payload_match` mapping. Both rules reach a number and an evidence list, so a second
copy would be a second chance for the stored and the recomputed report to disagree (SPEC §28).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.domain.common.values import FactValue
from app.domain.enums import RoleType
from app.domain.events.session_event import SessionEvent
from app.domain.scoring import evidence
from app.domain.scoring.context import CardFieldChange, ScoringContext
from app.domain.scoring.results import ScoreEvidence

EvaluatedAt = Literal["HANDOFF", "SESSION_END"]

__all__ = ["EvaluatedAt", "card_cutoff_evidence", "payload_matches"]


def card_cutoff_evidence(
    ctx: ScoringContext,
    change: CardFieldChange | None,
    note_ru: str,
    *roles: RoleType,
) -> ScoreEvidence:
    """Evidence for a card-field verdict: the revision, else the handoff, else the stage bound.

    D11 names exactly this ladder: a value the trainee typed is evidenced by the card revision it
    came from; a field never filled is evidenced by "the `HANDOFF_CREATED` for a field never
    filled"; a session that never handed off falls back to the event that closed the window.
    """
    if change is not None:
        return evidence.from_card_revision(change, note_ru)
    if ctx.handoff_event is not None:
        return evidence.from_snapshot(ctx.handoff_event, note_ru)
    return evidence.from_event(evidence.bounding_event(ctx, *roles), note_ru)


def payload_matches(event: SessionEvent, expected: Mapping[str, FactValue] | None) -> bool:
    """`True` when every key of `expected` is present in `event.payload` with that value.

    A subset match, not an equality: `to_payload_match`/`payload_match` name the few keys a rule
    cares about, and a payload that also carries offsets and correlation ids still matches.
    """
    if not expected:
        return True
    for key, wanted in expected.items():
        if key not in event.payload:
            return False
        actual = event.payload[key]
        if isinstance(actual, list | tuple) and isinstance(wanted, list):
            if [str(item) for item in actual] != [str(item) for item in wanted]:
                return False
            continue
        if actual != wanted and str(actual) != str(wanted):
            return False
    return True
