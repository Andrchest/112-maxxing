"""Opt-in real local llama.cpp smoke; only synthetic text, never production transcripts.

SIM_ML_AUDIT_SMOKE_URL=http://127.0.0.1:18189/v1 pytest backend/tests/test_ml_audit_live.py
"""

import os

import pytest
from app.application.reports.ml_audit import Criterion, MLAuditor, Rubric, Source
from app.inference.llm.llama_cpp_client import LlamaCppClient

pytestmark = pytest.mark.requires_models


async def test_real_local_llm_returns_one_forced_binary_token():
    url = os.environ.get("SIM_ML_AUDIT_SMOKE_URL")
    if not url:
        pytest.skip("set SIM_ML_AUDIT_SMOKE_URL to opt into real local inference")
    client = LlamaCppClient(
        base_url=url, model_name="local-smoke", n_ctx=8192, default_timeout_ms=60000
    )
    source = Source(
        id="operator:1", text="Назовите точный адрес происшествия, улицу и дом.", kind="dialogue"
    )
    rubric = Rubric(
        version="smoke-v1",
        criteria=(
            Criterion(
                id="address",
                category="Адрес",
                question="Запросил ли оператор адрес происшествия?",
                weight=1,
                source="dialogue",
            ),
        ),
    )
    try:
        result = await MLAuditor(client, timeout_ms=60000).evaluate(rubric, (source,), ())
    finally:
        await client.close()
    assert result.score_percent == 100, result.model_dump_json()
    assert result.results[0].decision_token == "да"
    assert result.evidence_method == "binary_token"
    assert result.results[0].evidence == ()  # HTTP never pretends to expose attention.
