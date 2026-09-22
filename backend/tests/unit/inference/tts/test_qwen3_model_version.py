"""`Qwen3TTS.model_version` reports what the worker actually serves, never a guess (E18-C).

`SIM_TTS_QWEN3_MODEL` picks the variant in the *worker's* process (`MODEL_VARIANTS` in
`tts_qwen3.server`: 1.7B, the owner's evaluated checkpoint, or 0.6B, the only one on this machine).
The adapter's own module constants are the 1.7B identity, so reporting them meant every
`CALLER_TTS_STARTED.tts_model` and every `inference_metrics.model_version` row claimed 1.7B on a box
serving 0.6B — a configured guess written into the audit record, which SPEC §27 does not allow.

`warm_up()` therefore asks the worker's `/health` and caches `"{model}@{revision}"`. `httpx.
MockTransport` stands in for the worker, so this runs under plain `make gate` (D13, no GPU).
"""

from __future__ import annotations

import httpx
import pytest
from app.inference.tts.qwen3_tts import MODEL_REVISION, Qwen3TTS

_BASE = "http://127.0.0.1:8112"
_SERVED_0_6B = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
_SERVED_0_6B_REVISION = "85e237c12c027371202489a0ec509ded67b5e4b5"


def _tts(handler) -> Qwen3TTS:  # type: ignore[no-untyped-def]
    return Qwen3TTS(
        base_url=_BASE,
        speaker="Serena",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _health_body(model: str, revision: str | None) -> dict[str, object]:
    return {
        "status": "ok",
        "model": model,
        "revision": revision,
        "device": "cuda:0",
        "loaded": True,
    }


def test_before_a_warm_up_the_pinned_constants_are_the_answer() -> None:
    """`model_version` is a synchronous property: an adapter must not do I/O inside one."""
    tts = _tts(lambda _r: httpx.Response(200))
    assert tts.model_version.endswith(f"@{MODEL_REVISION}")


async def test_a_warm_up_adopts_the_variant_the_worker_reports() -> None:
    """The 0.6B case: a worker serving 0.6B must not be recorded as 1.7B."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json=_health_body(_SERVED_0_6B, _SERVED_0_6B_REVISION))
        return httpx.Response(200)

    tts = _tts(handler)
    await tts.warm_up()
    assert tts.model_version == f"{_SERVED_0_6B}@{_SERVED_0_6B_REVISION}"
    # `/health` is asked **after** `/warm_up`, so `loaded` and the variant are both settled.
    assert seen == ["/warm_up", "/health"]


async def test_a_health_answer_without_a_revision_still_names_the_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json=_health_body(_SERVED_0_6B, None))
        return httpx.Response(200)

    tts = _tts(handler)
    await tts.warm_up()
    assert tts.model_version == _SERVED_0_6B


@pytest.mark.parametrize(
    "health",
    [
        httpx.Response(503),
        httpx.Response(200, json={"status": "ok"}),
        httpx.Response(200, json={"model": ""}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
    ids=["down", "no-model", "empty-model", "not-json", "not-an-object"],
)
async def test_an_unusable_health_answer_leaves_the_pinned_constants_in_place(
    health: httpx.Response,
) -> None:
    """A worker that cannot describe itself still gets to synthesise; the next warm-up retries."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return health
        return httpx.Response(200)

    tts = _tts(handler)
    await tts.warm_up()
    assert tts.model_version.endswith(f"@{MODEL_REVISION}")


async def test_refresh_never_raises_when_the_worker_is_unreachable() -> None:
    """It is called from `warm_up`, whose own failure mode is about synthesis, not identity."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200)

    tts = _tts(handler)
    assert await tts.refresh_model_version() == tts.model_version
    await tts.warm_up()  # must not raise either
