"""Card difficulty weights (HLD 70 §70.3.7, I3 E9a): the metadata, the heuristic, the proposals.

* `card_metadata` reads the ticket special variants right: a `…-decline` scenario has a scripted
  decline, a `…-card-error` one the ДДС card check, a base ticket neither;
* `heuristic_weight` is deterministic and stays in 1..10;
* a stored proposal set never changes a weight — only `Lesson.accept_weights` does, and only for
  the chosen positions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.domain.common.ids import LessonId, ScenarioVersionId, UserId
from app.domain.enums import RoleType, SessionMode
from app.domain.lesson.lesson import Lesson, create_lesson
from app.domain.lesson.plan import (
    Arrival,
    ArrivalKind,
    LessonParticipant,
    LessonPlanError,
    PlanEntry,
)
from app.domain.lesson.weights import (
    CardMetadata,
    ProposalSource,
    WeightProposal,
    WeightProposalSet,
    card_metadata,
    heuristic_weight,
    heuristic_weights,
)
from app.domain.session.variants import CardSource
from app.infrastructure.scenarios.yaml_loader import load_scenario_version

TICKETS = Path(__file__).resolve().parents[5] / "scenarios" / "tickets"
NOW = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
USER = UserId(uuid4())


def _meta(**overrides: object) -> CardMetadata:
    values: dict[str, object] = {
        "position": 1,
        "title": "Билет",
        "difficulty": 3,
        "card_source": CardSource.GENERATED_CARD,
        "role_chain": (RoleType.OPERATOR_112, RoleType.DDS),
        "required_service_count": 1,
        "optional_service_count": 0,
        "accept_within_ms": 30_000,
        "fill_within_ms": 180_000,
        "not_completed_after_ms": 172_800_000,
        "has_competence_decline": False,
        "has_card_check": False,
    }
    values.update(overrides)
    return CardMetadata.model_validate(values)


def _lesson(positions: int = 3) -> Lesson:
    return create_lesson(
        lesson_id=LessonId(uuid4()),
        title_ru="Занятие",
        created_by=USER,
        session_mode=SessionMode.SINGLE_ROLE,
        participants=[LessonParticipant(user_id=USER, assigned_role_type=RoleType.DDS)],
        scenario_plan=[
            PlanEntry(
                position=position,
                scenario_version_id=ScenarioVersionId(uuid4()),
                arrival=Arrival(kind=ArrivalKind.AT_OFFSET, offset_ms=0),
            )
            for position in range(1, positions + 1)
        ],
        created_at=NOW,
    )


def _proposals(*weights: int) -> WeightProposalSet:
    return WeightProposalSet(
        source=ProposalSource.HEURISTIC,
        requested_at=NOW,
        requested_by_user_id=USER,
        proposals=tuple(
            WeightProposal(position=index, proposed_weight=weight, reason_ru="Причина")
            for index, weight in enumerate(weights, start=1)
        ),
    )


# -- metadata ----------------------------------------------------------------------------------


def test_card_metadata_reads_the_ticket_special_variants() -> None:
    base = card_metadata(1, load_scenario_version(TICKETS / "ticket-01-call-1" / "v1.yaml"))
    decline = card_metadata(
        2, load_scenario_version(TICKETS / "ticket-01-call-1-decline" / "v1.yaml")
    )
    card_error = card_metadata(
        3, load_scenario_version(TICKETS / "ticket-01-call-2-card-error" / "v1.yaml")
    )
    assert (base.has_competence_decline, base.has_card_check) == (False, False)
    assert (decline.has_competence_decline, decline.has_card_check) == (True, False)
    assert (card_error.has_competence_decline, card_error.has_card_check) == (False, True)
    assert base.card_source is CardSource.GENERATED_CARD
    assert (base.provenance_source, base.provenance_ticket, base.provenance_call) == (
        "TICKET",
        1,
        1,
    )
    assert base.generation_candidate is True
    assert decline.position == 2 and decline.difficulty == 3


# -- heuristic ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "weight"),
    [
        ({"difficulty": 1}, 2),
        ({"difficulty": 3}, 6),
        ({"difficulty": 3, "required_service_count": 3}, 7),
        ({"difficulty": 3, "has_competence_decline": True}, 7),
        ({"difficulty": 3, "has_card_check": True}, 7),
        ({"difficulty": 3, "card_source": CardSource.CALLER_VOICE}, 7),
        (
            {
                "difficulty": 5,
                "required_service_count": 4,
                "has_competence_decline": True,
                "has_card_check": True,
            },
            10,
        ),
    ],
)
def test_the_heuristic_is_two_per_difficulty_plus_one_per_factor_in_one_to_ten(
    overrides: dict[str, object], weight: int
) -> None:
    proposal = heuristic_weight(_meta(**overrides))
    assert proposal.weight == weight
    assert proposal.reason_ru[0].isupper()
    if overrides.get("has_card_check"):
        assert "ДДС" in proposal.reason_ru, "the reason keeps its abbreviations upper-case"


def test_the_heuristic_is_deterministic_and_keeps_the_card_order() -> None:
    cards = [_meta(position=2, difficulty=4), _meta(position=1, difficulty=2)]
    assert heuristic_weights(cards) == heuristic_weights(cards)
    assert [item.position for item in heuristic_weights(cards)] == [2, 1]
    assert (
        "ограничено до 10"
        in heuristic_weight(
            _meta(difficulty=5, required_service_count=5, has_card_check=True)
        ).reason_ru
    )


# -- proposals and accept ----------------------------------------------------------------------


def test_storing_proposals_changes_no_weight() -> None:
    lesson = _lesson()
    stored = lesson.with_weight_proposals(_proposals(6, 8, 3))
    assert [entry.weight for entry in stored.scenario_plan] == [1.0, 1.0, 1.0]
    assert stored.weight_proposals is not None


def test_proposals_must_cover_exactly_the_plan_positions() -> None:
    with pytest.raises(LessonPlanError):
        _lesson().with_weight_proposals(_proposals(6, 8))


def test_accept_writes_only_the_chosen_weights_and_stamps_them() -> None:
    lesson = _lesson().with_weight_proposals(_proposals(6, 8, 3))
    accepted = lesson.accept_weights({1, 3}, NOW)
    assert [entry.weight for entry in accepted.scenario_plan] == [6.0, 1.0, 3.0]
    assert accepted.weight_proposals is not None
    stamps = [proposal.accepted_at for proposal in accepted.weight_proposals.proposals]
    assert stamps == [NOW, None, NOW]

    again = accepted.accept_weights({1, 2}, NOW + timedelta(minutes=1))
    assert [entry.weight for entry in again.scenario_plan] == [6.0, 8.0, 3.0]
    assert again.weight_proposals is not None
    assert again.weight_proposals.proposals[0].accepted_at == NOW, "the first accept is kept"


def test_accept_refuses_no_proposals_an_empty_or_an_unknown_selection() -> None:
    with pytest.raises(LessonPlanError):
        _lesson().accept_weights({1}, NOW)
    lesson = _lesson().with_weight_proposals(_proposals(6, 8, 3))
    with pytest.raises(LessonPlanError):
        lesson.accept_weights(set(), NOW)
    with pytest.raises(LessonPlanError):
        lesson.accept_weights({4}, NOW)
