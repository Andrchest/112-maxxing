"""LLM adapters over `app.application.ports.llm.LLMClient` (E13-B1).

`FakeLLM` is the gate's and every non-`requires_models` test's provider (D13); `LlamaCppClient` is
the only adapter that speaks to a real llama.cpp server, and only over loopback or a
compose-internal host name (SPEC §41, `validate_llm_base_url`).
"""

from __future__ import annotations

from app.inference.llm.errors import ExternalInferenceEndpointError
from app.inference.llm.fake_llm import FakeLLM, FakeLlmCall
from app.inference.llm.llama_cpp_client import LlamaCppClient, validate_llm_base_url

__all__ = [
    "ExternalInferenceEndpointError",
    "FakeLLM",
    "FakeLlmCall",
    "LlamaCppClient",
    "validate_llm_base_url",
]
