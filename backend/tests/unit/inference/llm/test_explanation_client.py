"""`build_explanation_llm_client` — provider selection and the loopback guard (epic E16-B,
SPEC §41, D13).

No real server anywhere in this file, exactly like `test_llama_cpp_client.py`'s own guard tests:
these run under plain `make gate`.
"""

from __future__ import annotations

import pytest
from app.config.settings import Settings
from app.inference.llm.explanation_client import (
    EXPLANATION_LLM_FAKE,
    EXPLANATION_LLM_LLAMA_CPP,
    build_explanation_llm_client,
)
from app.inference.llm.fake_llm import FakeLLM
from app.inference.llm.llama_cpp_client import LlamaCppClient


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://x/y",
        "redis_url": "redis://localhost",
        "jwt_secret": "s",
        "livekit_url": "ws://localhost:7880",
        "livekit_api_key": "k",
        "livekit_api_secret": "s",
        "llm_base_url": "http://127.0.0.1:8080/v1",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_the_fake_provider_is_the_default() -> None:
    client = build_explanation_llm_client(_settings())
    assert isinstance(client, FakeLLM)


def test_explicit_fake_provider() -> None:
    client = build_explanation_llm_client(_settings(explanation_llm_provider=EXPLANATION_LLM_FAKE))
    assert isinstance(client, FakeLLM)


def test_llama_cpp_provider_builds_a_real_client_over_a_loopback_url() -> None:
    client = build_explanation_llm_client(
        _settings(
            explanation_llm_provider=EXPLANATION_LLM_LLAMA_CPP,
            explanation_llm_base_url="http://127.0.0.1:8080/v1",
            explanation_llm_model_name="Qwen3-4B",
        )
    )
    assert isinstance(client, LlamaCppClient)
    assert client.model_name == "Qwen3-4B"


def test_llama_cpp_provider_rejects_a_non_loopback_base_url() -> None:
    with pytest.raises(Exception, match=r"not loopback|not a loopback"):
        build_explanation_llm_client(
            _settings(
                explanation_llm_provider=EXPLANATION_LLM_LLAMA_CPP,
                explanation_llm_base_url="https://api.openai.com/v1",
            )
        )


def test_an_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="SIM_EXPLANATION_LLM_PROVIDER"):
        build_explanation_llm_client(_settings(explanation_llm_provider="anthropic"))


def test_settings_defaults_are_the_documented_ones() -> None:
    settings = _settings()
    assert settings.explanation_llm_provider == EXPLANATION_LLM_FAKE
    assert settings.explanation_max_tokens == 400
    assert settings.explanation_temperature == 0.2
    assert settings.explanation_timeout_ms == 8000
