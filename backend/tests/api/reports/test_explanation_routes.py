"""API tests for `getReportExplanation` / `generateReportExplanation` (SPEC §2, §29; D11; R8).

Real Postgres/Redis, the production container, no port bound — this package's own `conftest.py`
(E16-A) gives a `completed` fixture: a two-trainee `MULTI_TRAINEE` session (`trainee1` =
`OPERATOR_112`, `trainee2` = `DDS`), `report_visible_to_trainee_before_release = False`, already
`SESSION_COMPLETED` and scored — which is also, for free, this file's release-gate fixture.

The container's `explanation_llm_client()` is cached lazily (`app.api.container.Container.
explanation_llm_client`); `_script` pre-seeds that cache with a scripted `FakeLLM` before the HTTP
call, since the default `SIM_EXPLANATION_LLM_PROVIDER=fake` builds an empty-script `FakeLLM()` that
answers `""` — which is itself exercised by `test_an_empty_completion_is_503`.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.inference.llm.fake_llm import FakeLLM

from .conftest import OperatorFlow, auth, release

pytestmark = pytest.mark.integration


def _script(flow: OperatorFlow, texts: list[Any]) -> FakeLLM:
    llm = FakeLLM(texts)
    flow.container._explanation_llm_client = llm  # type: ignore[attr-defined]
    return llm


async def generate(
    flow: OperatorFlow, *, token: str | None = None, json: dict[str, Any] | None = None
) -> httpx.Response:
    return await flow.client.post(
        f"/api/v1/reports/{flow.session_id}/explanation",
        headers=auth(token or flow.instructor_token),
        json=json,
    )


async def get_explanation(flow: OperatorFlow, *, token: str | None = None) -> httpx.Response:
    return await flow.client.get(
        f"/api/v1/reports/{flow.session_id}/explanation",
        headers=auth(token or flow.instructor_token),
    )


async def test_an_instructor_generates_a_trainee_explanation(completed: OperatorFlow) -> None:
    _script(completed, ["Стажёр справился хорошо."])

    response = await generate(completed, json={"audience": "TRAINEE"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["text_ru"] == "Стажёр справился хорошо."
    assert body["audience"] == "TRAINEE"
    assert body["llm_provider"] == "fake"
    assert body["llm_model"] == "fake-llm"
    assert len(body["score_report_checksum"]) == 64  # sha256 hex


async def test_the_default_audience_is_trainee(completed: OperatorFlow) -> None:
    _script(completed, ["По умолчанию."])

    response = await generate(completed, json={})

    assert response.status_code == 201, response.text
    assert response.json()["audience"] == "TRAINEE"


async def test_get_before_any_generation_is_404(completed: OperatorFlow) -> None:
    response = await get_explanation(completed)
    assert response.status_code == 404, response.text


async def test_get_returns_what_was_generated(completed: OperatorFlow) -> None:
    """Generated and fetched by the same caller (the instructor), so the audiences match — GET
    has no `audience` parameter and reads the caller's own role's row (HLD gap, see the module
    docstring of `app.api.routers.reports`)."""
    _script(completed, ["Сохранённый текст."])
    generated = await generate(completed, json={"audience": "INSTRUCTOR"})
    assert generated.status_code == 201, generated.text

    fetched = await get_explanation(completed)

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["text_ru"] == "Сохранённый текст."
    assert fetched.json()["score_report_checksum"] == generated.json()["score_report_checksum"]


async def test_an_instructor_gets_the_instructor_audience_explanation(
    completed: OperatorFlow,
) -> None:
    """No `audience` query param exists in the contract (HLD gap) — GET reads the caller's own
    role's audience, so an instructor never sees a trainee-toned explanation by accident."""
    _script(completed, ["Для стажёра.", "Для инструктора."])
    await generate(completed, json={"audience": "TRAINEE"})
    await generate(completed, json={"audience": "INSTRUCTOR"})

    fetched = await get_explanation(completed)

    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["audience"] == "INSTRUCTOR"
    assert fetched.json()["text_ru"] == "Для инструктора."


async def test_a_second_generation_without_regenerate_is_409(completed: OperatorFlow) -> None:
    _script(completed, ["first", "second"])
    first = await generate(completed, json={"audience": "TRAINEE"})
    assert first.status_code == 201, first.text

    second = await generate(completed, json={"audience": "TRAINEE"})

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "EXPLANATION_ALREADY_EXISTS"


async def test_regenerate_true_replaces_the_stored_explanation(completed: OperatorFlow) -> None:
    _script(completed, ["first", "second"])
    await generate(completed, json={"audience": "TRAINEE"})

    replaced = await generate(completed, json={"audience": "TRAINEE", "regenerate": True})

    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["text_ru"] == "second"


async def test_a_trainee_is_refused_before_release(completed: OperatorFlow) -> None:
    _script(completed, ["text"])

    generated = await generate(completed, token=completed.operator_token, json={})
    fetched = await get_explanation(completed, token=completed.operator_token)

    assert generated.status_code == 403, generated.text
    assert generated.json()["code"] == "REPORT_NOT_RELEASED"
    assert fetched.status_code == 403, fetched.text
    assert fetched.json()["code"] == "REPORT_NOT_RELEASED"


async def test_a_trainee_may_use_it_once_the_report_is_released(completed: OperatorFlow) -> None:
    released = await release(completed)
    assert released.status_code == 200, released.text
    _script(completed, ["Отчёт стажёра."])

    generated = await generate(completed, token=completed.operator_token, json={})

    assert generated.status_code == 201, generated.text
    assert generated.json()["text_ru"] == "Отчёт стажёра."


async def test_report_not_ready_before_the_session_is_completed(connected: OperatorFlow) -> None:
    response = await generate(connected, json={})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPORT_NOT_READY"


async def test_an_llm_timeout_is_503_and_nothing_is_stored(completed: OperatorFlow) -> None:
    _script(completed, [TimeoutError("no answer")])

    response = await generate(completed, json={"audience": "TRAINEE"})

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "LLM_UNAVAILABLE"
    assert (await get_explanation(completed)).status_code == 404


async def test_an_empty_completion_is_503(completed: OperatorFlow) -> None:
    _script(completed, [""])

    response = await generate(completed, json={"audience": "TRAINEE"})

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "LLM_UNAVAILABLE"
