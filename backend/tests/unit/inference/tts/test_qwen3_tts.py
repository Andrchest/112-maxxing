"""`Qwen3TTS` — the base-url guard, the wire shape and the chunk/cancel contract (this task's
brief, item 2).

No real worker anywhere in this file: `httpx.MockTransport` stands in for `workers/tts_qwen3`, so
these tests run under plain `make gate` (D13, no GPU, no `qwen-tts`/`torch==2.14.0`). The real
worker is only in `backend/tests/models/test_tts_contract.py` (marker `requires_models`).
"""

from __future__ import annotations

import json
import struct

import httpx
import pytest
from app.application.ports.tts import TtsTimeoutError, TtsUnavailableError, TtsVoiceSpec
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.inference.errors import InferenceOutOfMemoryError
from app.inference.tts.qwen3_tts import (
    OUTPUT_SAMPLE_RATE,
    Qwen3TTS,
    TtsQwen3EndpointError,
    validate_tts_qwen3_base_url,
)

_VALID_URLS = [
    "http://127.0.0.1:8112/",
    "http://127.5.5.5:8112",
    "http://localhost:8112",
    "http://tts-qwen3:8112",
]
_INVALID_URLS = [
    "http://localhost.evil.com:8112",
    "http://127.0.0.1.nip.io:8112",
    "https://api.openai.com/v1",
    "http://8.8.8.8:8112",
    "http://192.168.1.5:8112",
    "http:///nohost",
]


@pytest.mark.parametrize("url", _VALID_URLS)
def test_loopback_and_compose_internal_hosts_are_accepted(url: str) -> None:
    validate_tts_qwen3_base_url(url)  # must not raise


@pytest.mark.parametrize("url", _INVALID_URLS)
def test_everything_else_is_rejected(url: str) -> None:
    with pytest.raises(TtsQwen3EndpointError):
        validate_tts_qwen3_base_url(url)


def test_the_guard_bites_at_construction() -> None:
    with pytest.raises(TtsQwen3EndpointError):
        Qwen3TTS(base_url="https://api.openai.com/v1", speaker="Serena")


def test_construction_rejects_a_non_vendor_default_speaker() -> None:
    with pytest.raises(ValueError):
        Qwen3TTS(base_url="http://127.0.0.1:8112", speaker="NotASpeaker")


def _tone_pcm(n_samples: int) -> bytes:
    return struct.pack(f"<{n_samples}h", *([1000] * n_samples))


def _client(handler) -> Qwen3TTS:
    transport = httpx.MockTransport(handler)
    return Qwen3TTS(
        base_url="http://127.0.0.1:8112",
        speaker="Serena",
        client=httpx.AsyncClient(transport=transport),
    )


_VOICE = TtsVoiceSpec(voice_id="Serena", speaking_rate=1.0)


async def test_stream_sends_speaker_language_and_instruct() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        pcm = _tone_pcm(OUTPUT_SAMPLE_RATE // 2)  # 500 ms
        return httpx.Response(
            200,
            content=pcm,
            headers={
                "X-Sample-Rate": str(OUTPUT_SAMPLE_RATE),
                "X-Audio-Ms": "500",
                "X-Gen-Ms": "10",
            },
        )

    tts = _client(handler)
    stream = tts.stream("Здравствуйте.", _VOICE, request_id="r1", max_chunk_ms=40)
    chunks = [chunk async for chunk in stream]

    assert captured[0]["speaker"] == "Serena"
    assert captured[0]["language"] == "Russian"
    assert captured[0]["instruct"] == "Speak in a calm and composed manner."
    assert captured[0]["request_id"] == "r1"
    assert chunks  # at least one chunk
    for chunk in chunks:
        assert chunk.audio_ms <= 40
        assert chunk.alignment_is_exact is False
    assert chunks[-1].text_offset_end == len("Здравствуйте.")
    assert chunks[0].text_offset_start == 0


async def test_the_instruct_differs_between_two_emotions_carried_by_the_voice_spec() -> None:
    """MANAGER RULING on E14-B's gap 1 (E14 close-out item 4): emotion reaches the voice through
    `TtsVoiceSpec.emotion`, never through mutable provider state (`set_emotion()` is gone)."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=_tone_pcm(1000),
            headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)},
        )

    tts = _client(handler)
    calm_voice = TtsVoiceSpec(
        voice_id="Serena",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.CALM, stress_level=0.0),
    )
    panicked_voice = TtsVoiceSpec(
        voice_id="Serena",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.95),
    )
    _ = [chunk async for chunk in tts.stream("Алло.", calm_voice, request_id="r2a")]
    _ = [chunk async for chunk in tts.stream("Помогите!", panicked_voice, request_id="r2b")]

    assert captured[0]["instruct"] == "Speak in a calm and composed manner."
    assert captured[1]["instruct"] == "Speak in a panicked and hysterical manner."
    assert captured[0]["instruct"] != captured[1]["instruct"]


async def test_the_instruct_is_identical_for_identical_emotions() -> None:
    """Deterministic mapping: the same `EmotionState` always produces the same instruct text."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=_tone_pcm(1000),
            headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)},
        )

    tts = _client(handler)
    voice = TtsVoiceSpec(
        voice_id="Serena",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.WORRIED, stress_level=0.4),
    )
    _ = [chunk async for chunk in tts.stream("Один.", voice, request_id="r2c")]
    _ = [chunk async for chunk in tts.stream("Два.", voice, request_id="r2d")]

    assert captured[0]["instruct"] == captured[1]["instruct"]


async def test_a_none_emotion_on_the_voice_spec_synthesises_neutral() -> None:
    """`_VOICE` here carries no emotion — `stream()` must fall back to the neutral default."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            content=_tone_pcm(1000),
            headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)},
        )

    tts = _client(handler)
    assert _VOICE.emotion is None
    stream = tts.stream("Помогите!", _VOICE, request_id="r2e", max_chunk_ms=40)
    _ = [chunk async for chunk in stream]

    assert captured[0]["instruct"] == "Speak in a calm and composed manner."


async def test_stream_rejects_a_non_vendor_voice_id() -> None:
    tts = _client(lambda request: httpx.Response(200, content=b""))
    with pytest.raises(ValueError):
        tts.stream("тест", TtsVoiceSpec(voice_id="Bob", speaking_rate=1.0), request_id="r3")


async def test_stream_rejects_the_generic_provider_agnostic_default_voice_id() -> None:
    """`SIM_TTS_VOICE_ID`'s default (`"ru_female_1"`) is not a vendor speaker — see this task's
    report, "HLD gaps"."""
    tts = _client(lambda request: httpx.Response(200, content=b""))
    with pytest.raises(ValueError):
        tts.stream(
            "тест", TtsVoiceSpec(voice_id="ru_female_1", speaking_rate=1.0), request_id="r3b"
        )


async def test_an_empty_voice_id_falls_back_to_the_configured_default_speaker() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, content=_tone_pcm(1000), headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)}
        )

    tts = _client(handler)
    stream = tts.stream("тест", TtsVoiceSpec(voice_id="", speaking_rate=1.0), request_id="r3c")
    _ = [chunk async for chunk in stream]

    assert captured[0]["speaker"] == "Serena"  # the `_client()` fixture's default speaker


async def test_chunking_respects_max_chunk_ms() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pcm = _tone_pcm(OUTPUT_SAMPLE_RATE * 2)  # 2 seconds
        return httpx.Response(200, content=pcm, headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)})

    tts = _client(handler)
    stream = tts.stream(
        "Длинное предложение для проверки нарезки на части.",
        _VOICE,
        request_id="r4",
        max_chunk_ms=40,
    )
    chunks = [chunk async for chunk in stream]

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.audio_ms <= 40
    # chunk_index is contiguous from 0
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # offsets are non-decreasing and the last one reaches the end of the text
    assert chunks[-1].text_offset_end == len("Длинное предложение для проверки нарезки на части.")


async def test_a_503_with_oom_marker_raises_out_of_memory() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "tts_qwen3_unavailable", "message": "cuda oom"})

    tts = _client(handler)
    stream = tts.stream("тест", _VOICE, request_id="r5")
    with pytest.raises(InferenceOutOfMemoryError):
        _ = [chunk async for chunk in stream]


async def test_a_plain_503_raises_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "tts_qwen3_unavailable", "message": "down"})

    tts = _client(handler)
    stream = tts.stream("тест", _VOICE, request_id="r6")
    with pytest.raises(TtsUnavailableError):
        _ = [chunk async for chunk in stream]


async def test_a_timeout_raises_tts_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    tts = _client(handler)
    stream = tts.stream("тест", _VOICE, request_id="r7")
    with pytest.raises(TtsTimeoutError):
        _ = [chunk async for chunk in stream]


async def test_cancel_before_iteration_yields_nothing_and_sends_no_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=_tone_pcm(1000))

    tts = _client(handler)
    stream = tts.stream("тест", _VOICE, request_id="r8")
    await stream.cancel()
    chunks = [chunk async for chunk in stream]

    assert chunks == []
    assert calls == []


async def test_cancel_is_idempotent() -> None:
    tts = _client(lambda request: httpx.Response(200, content=b""))
    stream = tts.stream("тест", _VOICE, request_id="r9")
    await stream.cancel()
    await stream.cancel()  # must not raise
