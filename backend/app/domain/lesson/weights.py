"""Card difficulty weights: the metadata a proposal may read, the deterministic heuristic, and the
proposal set an instructor accepts (HLD 70 §70.3.7, I3 E9a; SPEC §2, D11).

A lesson card's `PlanEntry.weight` scales its points in the lesson report. An instructor sets it by
hand, or asks for **proposals** — an integer 1–10 and a short Russian reason per card — and
accepts the ones they want. A proposal is never applied by itself: only `Lesson.accept_weights`
writes `weight`, so the report (and every score) stays deterministic.

What a proposer may see is `CardMetadata` and nothing else: the scenario's title, difficulty,
card type, service counts, timers, special-variant flags and provenance. `card_metadata` is the
one place that reads a `ScenarioVersion` for this purpose and it names each field it copies, so
the world truth, the caller's knowledge and the disclosure rules have no path into a prompt.

`heuristic_weight` is the deterministic proposer: the LLM adapter's fallback on any failure, and
the proposer the gate runs.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.ids import UserId
from app.domain.dds.response import ServiceResponseStatus
from app.domain.enums import EvaluatorType, RoleType
from app.domain.events.types import EventType
from app.domain.lesson.plan import LessonPlanError
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.variants import CardSource, DdsCardCheck

__all__ = [
    "MAX_PROPOSED_WEIGHT",
    "MIN_PROPOSED_WEIGHT",
    "CardMetadata",
    "ProposalSource",
    "ProposedWeight",
    "WeightProposal",
    "WeightProposalSet",
    "card_metadata",
    "heuristic_weight",
    "heuristic_weights",
]

MIN_PROPOSED_WEIGHT = 1
MAX_PROPOSED_WEIGHT = 10


class ProposalSource(str, Enum):
    """Who produced a proposal set."""

    LLM = "LLM"
    HEURISTIC = "HEURISTIC"


class CardMetadata(BaseModel):
    """Everything a weight proposer may read about one plan entry — scenario metadata only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int = Field(ge=1)
    title: str
    difficulty: int = Field(ge=1, le=5)
    card_source: CardSource
    """The version's default card type: a generated card, or an AI-voiced caller."""
    role_chain: tuple[RoleType, ...]
    required_service_count: int = Field(ge=0)
    optional_service_count: int = Field(ge=0)
    accept_within_ms: int
    fill_within_ms: int
    not_completed_after_ms: int
    has_competence_decline: bool
    """The task expects a service's «Не принята» — a decline by competence (the `…-decline`
    special variant), read off the scoring rules' declared expectations."""
    has_card_check: bool
    """The ДДС card check is on by default (the `…-card-error` special variant)."""
    provenance_source: str | None = None
    provenance_ticket: int | None = None
    provenance_call: int | None = None
    generation_candidate: bool | None = None


def card_metadata(position: int, version: ScenarioVersion) -> CardMetadata:
    """The metadata of one plan entry's scenario version, each field named — never a dump.

    The competence-decline flag comes from the scoring rules (a `WORKFLOW_ACTION` rule expecting
    a `DDS_SERVICE_STATUS_SET` to `NOT_ACCEPTED`), not from `expected_response.responders`: the
    scripted responders are runner-side data only (HLD 70 §70.1 INV 3).
    """
    competence_decline = any(
        rule.evaluator_type is EvaluatorType.WORKFLOW_ACTION
        and rule.config.get("event_type") == EventType.DDS_SERVICE_STATUS_SET.value
        and _new_status(rule.config) == ServiceResponseStatus.NOT_ACCEPTED.value
        for rule in version.scoring_rules
    )
    default = version.scenario_variants.default
    timers = version.card_timers
    provenance = version.provenance
    return CardMetadata(
        position=position,
        title=version.title,
        difficulty=version.difficulty,
        card_source=default.card_source,
        role_chain=version.role_chain,
        required_service_count=len(version.expected_response.required_services),
        optional_service_count=len(version.expected_response.optional_services),
        accept_within_ms=timers.accept_within_ms,
        fill_within_ms=timers.fill_within_ms,
        not_completed_after_ms=timers.not_completed_after_ms,
        has_competence_decline=competence_decline,
        has_card_check=default.dds_card_check is DdsCardCheck.ON,
        provenance_source=None if provenance is None else provenance.source.value,
        provenance_ticket=None if provenance is None else provenance.ticket,
        provenance_call=None if provenance is None else provenance.call,
        generation_candidate=None if provenance is None else provenance.generation_candidate,
    )


def _new_status(config: Mapping[str, object]) -> object:
    match = config.get("payload_match")
    return match.get("new_status") if isinstance(match, Mapping) else None


class ProposedWeight(BaseModel):
    """One proposer's answer for one card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int = Field(ge=1)
    weight: int = Field(ge=MIN_PROPOSED_WEIGHT, le=MAX_PROPOSED_WEIGHT)
    reason_ru: str = Field(min_length=1, max_length=400)


def heuristic_weight(card: CardMetadata) -> ProposedWeight:
    """The deterministic proposal: `2 × difficulty`, +1 for each complicating factor, in 1..10.

    Factors: three or more required services, an AI-voiced caller with the 112 interview, an
    expected competence decline, a card deliberately carrying an error for the ДДС to catch.
    """
    weight = 2 * card.difficulty
    reasons = [f"сложность {card.difficulty} из 5 — {2 * card.difficulty} б."]
    if card.required_service_count >= 3:
        weight += 1
        reasons.append(f"служб: {card.required_service_count} (+1)")
    if card.card_source is CardSource.CALLER_VOICE and RoleType.OPERATOR_112 in card.role_chain:
        weight += 1
        reasons.append("разговор с заявителем (+1)")
    if card.has_competence_decline:
        weight += 1
        reasons.append("отказ службы по компетенции (+1)")
    if card.has_card_check:
        weight += 1
        reasons.append("ошибка в карточке для проверки ДДС (+1)")
    clamped = max(MIN_PROPOSED_WEIGHT, min(MAX_PROPOSED_WEIGHT, weight))
    reason = "; ".join(reasons)
    if clamped != weight:
        reason += f"; ограничено до {clamped}"
    return ProposedWeight(
        position=card.position, weight=clamped, reason_ru=reason[0].upper() + reason[1:]
    )


def heuristic_weights(cards: Sequence[CardMetadata]) -> tuple[ProposedWeight, ...]:
    """`heuristic_weight` for every card, in the order given."""
    return tuple(heuristic_weight(card) for card in cards)


class WeightProposal(BaseModel):
    """One stored proposal: the proposer's answer plus when the instructor accepted it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: int = Field(ge=1)
    proposed_weight: int = Field(ge=MIN_PROPOSED_WEIGHT, le=MAX_PROPOSED_WEIGHT)
    reason_ru: str = Field(min_length=1)
    accepted_at: datetime | None = None


class WeightProposalSet(BaseModel):
    """The latest proposal request of a lesson (`lessons.weight_proposals`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: ProposalSource
    model_name: str | None = None
    """The LLM's model name when `source` is `LLM`; `None` for the heuristic."""
    fallback_reason: str | None = None
    """Why the heuristic answered instead of the LLM (`None` when nothing failed)."""
    requested_at: datetime
    requested_by_user_id: UserId
    proposals: tuple[WeightProposal, ...]

    def accept(self, positions: Collection[int], accepted_at: datetime) -> WeightProposalSet:
        """Mark `positions` accepted (`LessonPlanError` for an empty or unknown selection).

        Accepting an accepted proposal again keeps its first `accepted_at`.
        """
        if not positions:
            raise LessonPlanError("choose at least one proposal to accept")
        known = {proposal.position for proposal in self.proposals}
        unknown = sorted(set(positions) - known)
        if unknown:
            raise LessonPlanError(f"no weight proposal for positions {unknown}")
        return self.model_copy(
            update={
                "proposals": tuple(
                    proposal.model_copy(update={"accepted_at": accepted_at})
                    if proposal.position in positions and proposal.accepted_at is None
                    else proposal
                    for proposal in self.proposals
                )
            }
        )
