from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.application.ports.llm import LlmCompletion, LlmUsage
from app.application.reports.ml_audit import (
    BINARY_GRAMMAR,
    Criterion,
    CriterionResult,
    MLAuditor,
    Rubric,
    Source,
    report_sources,
)

SOURCE = Source(id="transcript:1", text="🙂 Там никто не ранен? Кровь есть?", kind="dialogue")
CRITERION = Criterion(
    id="victims",
    category="Сбор данных",
    question="Есть ли пострадавшие?",
    weight=0.4,
    source="dialogue",
)
RUBRIC = Rubric(version="test-v1", criteria=(CRITERION,))


def llm(text, *, finish_reason="length", tokens=1):
    return SimpleNamespace(
        model_name="test-model",
        n_ctx=32768,
        complete=AsyncMock(
            return_value=LlmCompletion(
                text=text,
                finish_reason=finish_reason,
                usage=LlmUsage(1, tokens),
                model="test-model",
                request_id="test",
            )
        ),
    )


@pytest.mark.parametrize("token,score", [("да", 100), ("нет", 0)])
async def test_exactly_one_forced_binary_token_no_generated_quotes_or_scores(token, score):
    model = llm(token)
    result = await MLAuditor(model).evaluate(RUBRIC, (SOURCE,), ("Пожар",))
    assert result.score_percent == score
    assert result.coverage_percent == 100
    assert result.results[0].decision_token == token
    assert result.results[0].evidence == ()  # HTTP adapter does not invent attention.
    assert result.evidence_method == "binary_token"
    kwargs = model.complete.call_args.kwargs
    assert kwargs["max_tokens"] == 1
    assert kwargs["extra_body"]["grammar"] == BINARY_GRAMMAR
    assert kwargs["temperature"] == 0
    assert "weight" not in model.complete.call_args.args[0][1].content


@pytest.mark.parametrize("response", ["не уверен", "null", "да, потому что", "true", "", "Да"])
async def test_third_answer_or_prose_is_protocol_error_not_a_model_grade(response):
    result = await MLAuditor(llm(response)).evaluate(RUBRIC, (SOURCE,), ())
    assert result.score_percent is None
    assert result.coverage_percent == 0
    assert result.results[0].issue == "inference_error"
    assert result.results[0].decision_token is None


async def test_multiple_generated_tokens_are_rejected_even_if_text_looks_binary():
    result = await MLAuditor(llm("да", tokens=2)).evaluate(RUBRIC, (SOURCE,), ())
    assert result.results[0].issue == "inference_error"


async def test_healthbench_weighted_total_is_computed_in_code():
    model = llm("нет")
    model.complete.side_effect = [
        model.complete.return_value,
        replace(model.complete.return_value, text="да"),
    ]
    rubric = Rubric(
        version="weights",
        criteria=(
            CRITERION,
            CRITERION.model_copy(update={"id": "second", "weight": 0.6}),
        ),
    )
    result = await MLAuditor(model).evaluate(rubric, (SOURCE,), ())
    assert result.score_percent == 60
    assert result.total_weight == 1
    assert result.earned_weight == 0.6
    assert [r.awarded_weight for r in result.results] == [0, 0.6]
    assert result.categories[0].score_percent == 60


async def test_card_cannot_prove_interview_question():
    model = llm("да")
    result = await MLAuditor(model).evaluate(
        RUBRIC,
        (Source(id="card:address", text="Ленина 1", kind="card"),),
        (),
    )
    assert result.results[0].issue == "no_source"
    model.complete.assert_not_called()


async def test_fake_provider_is_not_a_real_score():
    model = llm("нет")
    result = await MLAuditor(model).evaluate(RUBRIC, (SOURCE,), (), provider_available=False)
    assert result.score_percent is None
    model.complete.assert_not_called()


async def test_timeout_is_technical_failure_not_no():
    model = llm("да")
    model.complete.side_effect = TimeoutError()
    result = await MLAuditor(model).evaluate(RUBRIC, (SOURCE,), ())
    assert result.score_percent is None
    assert result.results[0].passed is None


async def test_context_is_never_silently_truncated():
    model = llm("да")
    model.n_ctx = 10
    result = await MLAuditor(model).evaluate(RUBRIC, (SOURCE,), ())
    assert result.results[0].issue == "context_too_large"
    model.complete.assert_not_called()


def test_rubric_validation_and_verdict_consistency():
    with pytest.raises(ValueError):
        Rubric(version="x", criteria=(CRITERION, CRITERION))
    for weight in [0, -1, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            Criterion(**{**CRITERION.model_dump(), "weight": weight})
    with pytest.raises(ValueError):
        CriterionResult(criterion=CRITERION, passed=True, decision_token="нет")


def test_sources_use_only_visible_final_operator_text_card_and_handoff():
    report = SimpleNamespace(
        session=SimpleNamespace(role_chain=("OPERATOR_112",)),
        timeline=[SimpleNamespace(event_type="DDS_CALL_STARTED", call_id="dds")],
        transcript=[
            SimpleNamespace(
                id="a", speaker="OPERATOR", text="Шумный текст", is_final=True, call_id=None
            ),
            SimpleNamespace(id="b", speaker="CALLER", text="Контекст", is_final=True, call_id=None),
            SimpleNamespace(
                id="c", speaker="OPERATOR", text="черновик", is_final=False, call_id=None
            ),
            SimpleNamespace(
                id="d", speaker="OPERATOR", text="Другой стажёр", is_final=True, call_id="dds"
            ),
        ],
        final_card=SimpleNamespace(values={"address": "Касмынафтов 1", "empty": None}),
        handoff=SimpleNamespace(recipient_services=("FIRE", "AMBULANCE")),
    )
    sources, context = report_sources(report)
    assert [s.text for s in sources] == [
        "Шумный текст",
        "Касмынафтов 1",
        '["FIRE", "AMBULANCE"]',
    ]
    assert context == ("Контекст",)
    report.transcript = []
    report.final_card.values = {}
    assert report_sources(report) == ((), ())
    report.session.role_chain = ("DDS",)
    assert report_sources(report) == ((), ())
