"""`build_explanation_llm_client` — the BACKEND process's own `LLMClient`, for score explanations
only (epic E16-B, SPEC §2, §29, §41; D9, D10, D13).

`generateReportExplanation` is a backend HTTP route, not a voice-agent turn-loop call: the voice
path's `SIM_LLM_*` interpreter/generator client is built by `workers.voice_agent.voice_agent.
providers.build_llm` and lives entirely inside the separate voice-agent worker process (D9). This
module is the backend's *own* factory, over its own `SIM_EXPLANATION_*` settings — its shape is
copied from `providers.py::build_llm`'s branching (this task's brief said to read that function
for the knowledge, not to import it — `workers/` is a different process and a different venv, and
`backend/tools/check_imports.py` forbids `app` from depending on it), but it builds the very same
`LlamaCppClient`/`FakeLLM` classes this package (`app.inference.llm`) already has, imported lazily
exactly as `providers.py` does: a plain `app.inference.llm` import must work with no ML extra
installed (E12's rule extends to this client, though `LlamaCppClient` itself only needs `httpx`,
already a hard dependency).
"""

from __future__ import annotations

from app.application.ports.llm import LLMClient
from app.config.settings import Settings

__all__ = ["EXPLANATION_LLM_FAKE", "EXPLANATION_LLM_LLAMA_CPP", "build_explanation_llm_client"]

#: `SIM_EXPLANATION_LLM_PROVIDER` values. `fake` is the gate's and every non-`requires_models`
#: test's provider (D13); `llama_cpp` is the real local server.
EXPLANATION_LLM_FAKE = "fake"
EXPLANATION_LLM_LLAMA_CPP = "llama_cpp"


def build_explanation_llm_client(settings: Settings) -> LLMClient:
    """The `LLMClient` named by `SIM_EXPLANATION_LLM_PROVIDER`.

    `llama_cpp` validates `SIM_EXPLANATION_LLM_BASE_URL` at construction — loopback or a
    compose-internal host name only, never at call time (SPEC §41) — through the same
    `LlamaCppClient`/`validate_llm_base_url` the voice-agent's interpreter/generator use: one
    validation rule, a second independent instance of it, not a second implementation.
    """
    provider = settings.explanation_llm_provider
    if provider == EXPLANATION_LLM_FAKE:
        from app.inference.llm.fake_llm import FakeLLM

        return FakeLLM()
    if provider == EXPLANATION_LLM_LLAMA_CPP:
        from app.inference.llm.llama_cpp_client import LlamaCppClient

        return LlamaCppClient(
            base_url=settings.explanation_llm_base_url,
            model_name=settings.explanation_llm_model_name,
            n_ctx=settings.llm_n_ctx,
            default_timeout_ms=settings.explanation_timeout_ms,
            allowed_internal_hosts=settings.llm_allowed_internal_hosts,
        )
    raise ValueError(
        f"SIM_EXPLANATION_LLM_PROVIDER={provider!r} is not an LLM provider; "
        f"use {EXPLANATION_LLM_FAKE!r} or {EXPLANATION_LLM_LLAMA_CPP!r}"
    )
