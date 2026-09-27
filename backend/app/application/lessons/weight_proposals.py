"""Difficulty-weight proposals — `requestWeightProposals`, `getWeightProposals`,
`acceptWeightProposals` (HLD 70 §70.3.7, I3 E9a; SPEC §2, D11).

F-15: «сложность задания должна определяться критерием весов… либо задаваться вручную… либо…
искусственный интеллект… должен предложить преподавателю». The flow:

1. **request** — read each plan entry's scenario version and reduce it to `CardMetadata` (the only
   thing a proposer may see), close the transaction, ask the `WeightProposer` once for the whole
   lesson (the LLM adapter answers the heuristic on any failure), then store the answer as the
   lesson's `weight_proposals`, replacing any earlier set. **No weight changes.**
2. **get** — the stored set with each card's current weight beside its proposal.
3. **accept** — the instructor's chosen positions: `Lesson.accept_weights` writes each chosen
   proposal into `PlanEntry.weight`. That is the only path from a proposal to a weight, and the
   lesson report reads only `PlanEntry.weight` — so the report stays deterministic and a proposal
   never scores anything by itself.

The creator of the lesson or an ADMIN only (`403 FORBIDDEN_FOR_ROLE`): weights change the lesson's
report, which is the creator's. Allowed in every lesson state; nothing is rescored — the report
sums the stored card scores by weight when it is read.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.lessons.errors import LessonNotFoundError, require_creator_or_admin
from app.application.ports.clock import Clock
from app.application.ports.id_generator import IdGenerator
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.weight_proposer import WeightProposer
from app.domain.common.errors import DomainError
from app.domain.common.ids import LessonId, ScenarioVersionId, UserId
from app.domain.lesson.lesson import Lesson
from app.domain.lesson.weights import (
    CardMetadata,
    ProposalSource,
    WeightProposal,
    WeightProposalSet,
    card_metadata,
)
from app.domain.scenario.version import ScenarioVersion

__all__ = [
    "AcceptWeightProposals",
    "GetWeightProposals",
    "RequestWeightProposals",
    "WeightProposalLineView",
    "WeightProposalsNotFoundError",
    "WeightProposalsView",
]


class WeightProposalsNotFoundError(DomainError):
    """The lesson has no stored proposals yet (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, lesson_id: LessonId) -> None:
        self.lesson_id = lesson_id
        super().__init__(f"lesson {lesson_id} has no weight proposals")


@dataclass(frozen=True)
class WeightProposalLineView:
    """One card: its current weight beside the proposal."""

    position: int
    scenario_version_id: ScenarioVersionId
    current_weight: float
    proposed_weight: int
    reason_ru: str
    accepted_at: datetime | None


@dataclass(frozen=True)
class WeightProposalsView:
    """`WeightProposalSet` as application data."""

    lesson_id: LessonId
    source: ProposalSource
    model_name: str | None
    fallback_reason: str | None
    requested_at: datetime
    requested_by_user_id: UserId
    proposals: tuple[WeightProposalLineView, ...]


def proposals_view(lesson: Lesson) -> WeightProposalsView:
    """The lesson's stored set beside its current weights (`WeightProposalsNotFoundError`)."""
    stored = lesson.weight_proposals
    if stored is None:
        raise WeightProposalsNotFoundError(lesson.lesson_id)
    return WeightProposalsView(
        lesson_id=lesson.lesson_id,
        source=stored.source,
        model_name=stored.model_name,
        fallback_reason=stored.fallback_reason,
        requested_at=stored.requested_at,
        requested_by_user_id=stored.requested_by_user_id,
        proposals=tuple(
            WeightProposalLineView(
                position=proposal.position,
                scenario_version_id=lesson.entry(proposal.position).scenario_version_id,
                current_weight=lesson.entry(proposal.position).weight,
                proposed_weight=proposal.proposed_weight,
                reason_ru=proposal.reason_ru,
                accepted_at=proposal.accepted_at,
            )
            for proposal in stored.proposals
        ),
    )


async def _load(uow: UnitOfWork, lesson_id: LessonId, *, for_update: bool = False) -> Lesson:
    if for_update:
        lesson = await uow.lessons.get_for_update(lesson_id)
    else:
        lesson = await uow.lessons.get(lesson_id)
    if lesson is None:
        raise LessonNotFoundError(lesson_id)
    return lesson


async def lesson_card_metadata(uow: UnitOfWork, lesson: Lesson) -> tuple[CardMetadata, ...]:
    """Every plan entry's `CardMetadata`, in `position` order — the proposer's whole input."""
    cards: list[CardMetadata] = []
    for entry in lesson.scenario_plan:
        document = await uow.scenarios.get_version_document(entry.scenario_version_id)
        if document is None:  # pragma: no cover - the FK and createLesson guarantee it
            raise LessonNotFoundError(lesson.lesson_id)
        version = ScenarioVersion.model_validate(dict(document))
        cards.append(card_metadata(entry.position, version))
    return tuple(cards)


class RequestWeightProposals:
    """`requestWeightProposals` — ask the proposer once, store the answer, change no weight."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        proposer: WeightProposer,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._proposer = proposer
        self._clock = clock
        self._ids = ids

    async def __call__(self, lesson_id: LessonId, user: AuthenticatedUser) -> WeightProposalsView:
        async with self._unit_of_work() as uow:
            lesson = await _load(uow, lesson_id)
            require_creator_or_admin(lesson, user)  # I5 E39: NOT_RESOURCE_OWNER
            cards = await lesson_card_metadata(uow, lesson)
            await uow.commit()

        # No transaction is held across the model call.
        answer = await self._proposer.propose(cards, request_id=str(self._ids.new()))
        proposals = WeightProposalSet(
            source=answer.source,
            model_name=answer.model_name,
            fallback_reason=answer.fallback_reason,
            requested_at=self._clock.now(),
            requested_by_user_id=user.user_id,
            proposals=tuple(
                WeightProposal(
                    position=item.position, proposed_weight=item.weight, reason_ru=item.reason_ru
                )
                for item in answer.items
            ),
        )

        async with self._unit_of_work() as uow:
            lesson = await _load(uow, lesson_id, for_update=True)
            stored = lesson.with_weight_proposals(proposals)
            await uow.lessons.save_weights(stored)
            await uow.commit()
        return proposals_view(stored)


class GetWeightProposals:
    """`getWeightProposals` — INSTRUCTOR/ADMIN (the router's account gate)."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, lesson_id: LessonId) -> WeightProposalsView:
        async with self._unit_of_work() as uow:
            lesson = await _load(uow, lesson_id)
            await uow.commit()
        return proposals_view(lesson)


class AcceptWeightProposals:
    """`acceptWeightProposals` — the chosen proposals become `PlanEntry.weight`."""

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    async def __call__(
        self, lesson_id: LessonId, positions: Collection[int], user: AuthenticatedUser
    ) -> WeightProposalsView:
        async with self._unit_of_work() as uow:
            lesson = await _load(uow, lesson_id, for_update=True)
            require_creator_or_admin(lesson, user)  # I5 E39: NOT_RESOURCE_OWNER
            if lesson.weight_proposals is None:
                raise WeightProposalsNotFoundError(lesson_id)
            accepted = lesson.accept_weights(frozenset(positions), self._clock.now())
            await uow.lessons.save_weights(accepted)
            await uow.commit()
        return proposals_view(accepted)
