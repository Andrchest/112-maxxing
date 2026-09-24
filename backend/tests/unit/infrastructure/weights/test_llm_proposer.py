"""`LlmWeightProposer` (HLD 70 §70.3.7, I3 E9a): one constrained call per lesson, the heuristic on
any failure.

* a valid answer is the LLM's, in plan order, with the model's name;
* every failure — unavailable, timeout, cut off, not JSON, a missing or doubled position, a weight
  outside 1..10 or not an integer — answers exactly `heuristic_weights(cards)` with its reason;
* the call is one `complete()` with `RESPONSE_FORMAT` and `build_messages(cards)`.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.application.lessons.weight_prompt import RESPONSE_FORMAT, build_messages
from app.application.ports.llm import LlmTimeoutError, LlmUnavailableError
from app.domain.enums import RoleType
from app.domain.lesson.weights import CardMetadata, ProposalSource, heuristic_weights
from app.domain.session.variants import CardSource
from app.inference.llm.fake_llm import FakeLLM
from app.infrastructure.weights.heuristic_proposer import HeuristicWeightProposer
from app.infrastructure.weights.llm_proposer import LlmWeightProposer


def _card(position: int, difficulty: int) -> CardMetadata:
    return CardMetadata(
        position=position,
        title=f"Билет {position}",
        difficulty=difficulty,
        card_source=CardSource.GENERATED_CARD,
        role_chain=(RoleType.OPERATOR_112, RoleType.DDS),
        required_service_count=2,
        optional_service_count=0,
        accept_within_ms=30_000,
        fill_within_ms=180_000,
        not_completed_after_ms=172_800_000,
        has_competence_decline=False,
        has_card_check=False,
    )


CARDS = [_card(1, 2), _card(2, 4), _card(3, 5)]


def _proposer(llm: FakeLLM) -> LlmWeightProposer:
    return LlmWeightProposer(
        llm, HeuristicWeightProposer(), max_tokens=900, temperature=0.2, timeout_ms=5_000
    )


def _answer(*items: tuple[Any, Any, Any]) -> dict[str, Any]:
    return {
        "proposals": [
            {"position": position, "weight": weight, "reason_ru": reason}
            for position, weight, reason in items
        ]
    }


async def test_a_valid_answer_is_the_llms_in_plan_order_after_one_constrained_call() -> None:
    llm = FakeLLM([_answer((3, 9, "Сложно"), (1, 3, "Просто"), (2, 6, "Средне"))])
    answer = await _proposer(llm).propose(CARDS, request_id="r-1")
    assert answer.source is ProposalSource.LLM
    assert answer.model_name == "fake-llm" and answer.fallback_reason is None
    assert [(item.position, item.weight) for item in answer.items] == [(1, 3), (2, 6), (3, 9)]
    [call] = llm.calls
    assert call.response_format == RESPONSE_FORMAT
    assert call.messages == build_messages(CARDS)
    assert call.request_id == "r-1"


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        (LlmUnavailableError("down"), "LLM_UNAVAILABLE"),
        (RuntimeError("anything"), "LLM_UNAVAILABLE"),
        (LlmTimeoutError("slow"), "LLM_TIMEOUT"),
        (TimeoutError(), "LLM_TIMEOUT"),
        ("", "LLM_INVALID_OUTPUT"),
        ("не JSON", "LLM_INVALID_OUTPUT"),
        ({"weights": []}, "LLM_INVALID_OUTPUT"),
        (_answer((1, 3, "a"), (2, 6, "b")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 3, "a"), (1, 3, "a"), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 11, "a"), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 0, "a"), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 2.5, "a"), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, True, "a"), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 3, " "), (2, 6, "b"), (3, 9, "c")), "LLM_INVALID_OUTPUT"),
        (_answer((1, 3, "a"), (2, 6, "b"), (4, 9, "c")), "LLM_INVALID_OUTPUT"),
    ],
)
async def test_any_failure_answers_the_heuristic(script: Any, reason: str) -> None:
    answer = await _proposer(FakeLLM([script])).propose(CARDS, request_id="r-2")
    assert answer.source is ProposalSource.HEURISTIC
    assert answer.fallback_reason == reason
    assert answer.model_name is None
    assert answer.items == heuristic_weights(CARDS)


async def test_the_heuristic_adapter_needs_no_model() -> None:
    answer = await HeuristicWeightProposer().propose(CARDS, request_id="r-3")
    assert answer.source is ProposalSource.HEURISTIC and answer.fallback_reason is None
    assert [item.weight for item in answer.items] == [4, 8, 10]
