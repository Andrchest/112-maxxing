"""`LlamaCppClient`-construction error (SPEC §41).

`LlmTimeoutError` / `LlmUnavailableError` (the per-call failures) live in
`app.application.ports.llm` instead, because the interpreter (`app.application.dialogue`) needs to
classify them into `InferenceMetric.status` and `app.application` may not import `app.inference`
(D2). `ExternalInferenceEndpointError` is construction-time only — nothing outside
`app.inference.llm` ever constructs a `LlamaCppClient` or calls `validate_llm_base_url` — so it has
no such constraint and stays here.
"""

from __future__ import annotations

__all__ = ["ExternalInferenceEndpointError"]


class ExternalInferenceEndpointError(RuntimeError):
    """`base_url` is neither loopback nor a configured compose-internal host name (SPEC §41).

    Raised at `LlamaCppClient` construction, never later: "Core demo must work without external AI
    APIs" is a start-up guarantee, not a runtime check that a misconfigured deployment could race.
    """
