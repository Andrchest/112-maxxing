"""`Qwen3TTS` — the base-url guard, the wire shape and the chunk/cancel contract (this task's
brief, item 2).

No real worker anywhere in this file: `httpx.MockTransport` stands in for `workers/tts_qwen3`, so
these tests run under plain `make gate` (D13, no GPU, no `qwen-tts`/`torch==2.14.0`). The real
worker is only in `backend/tests/models/test_tts_contract.py` (marker `requires_models`).
"""

from __future__ import annotations

import json
import logging
import struct

import httpx
import pytest
from app.application.ports.tts import TtsTimeoutError, TtsUnavailableError, TtsVoiceSpec
from app.domain.caller.emotion import EmotionState
from app.domain.enums import CallerVoiceStyle, EmotionLabel
from app.inference.errors import InferenceOutOfMemoryError
from app.inference.tts.instruct import STYLE_PRESETS
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

    assert captured[0]["speaker"] == "serena"
    assert captured[0]["language"] == "Russian"
    assert captured[0]["instruct"] == STYLE_PRESETS["calm_fast"]
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

    assert captured[0]["instruct"] == STYLE_PRESETS["calm_fast"]
    assert captured[1]["instruct"] == STYLE_PRESETS["panic_fast"]
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

    assert captured[0]["instruct"] == STYLE_PRESETS["calm_fast"]


async def test_the_scenario_pain_voice_style_sends_the_pain_preset() -> None:
    """I8 V0: `TtsVoiceSpec.voice_style = PAIN` (the scenario's `caller_profile.voice_style`)
    overrides the emotion table with `pain_gasp`."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, content=_tone_pcm(1000), headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)}
        )

    tts = _client(handler)
    voice = TtsVoiceSpec(
        voice_id="serena",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.WORRIED, stress_level=0.4),
        voice_style=CallerVoiceStyle.PAIN,
    )
    _ = [chunk async for chunk in tts.stream("Мне больно.", voice, request_id="r2f")]

    assert captured[0]["instruct"] == STYLE_PRESETS["pain_gasp"]


def test_speaker_names_are_matched_case_insensitively() -> None:
    """I8 V0: an operator's `.env` spelling (`Serena`) still constructs; Vivian is gone."""
    tts = Qwen3TTS(base_url="http://127.0.0.1:8112", speaker="Serena", default_voice="ERIC")
    assert tts.native_voice_id("") == "eric"
    with pytest.raises(ValueError):
        Qwen3TTS(base_url="http://127.0.0.1:8112", speaker="Vivian")


# --- E20-G/G6: `voice_id` is a SCENARIO-LOGICAL id, resolved through the profile's voice_map ----
# These four replace the two tests that asserted the OLD contract (an unmapped `voice_id` raised
# `ValueError`). That contract is what left the shipped DEV_3060TI caller silent on E20-C's §46
# walk: the demo scenario casts `ru_female_adult_01`, which is not a vendor speaker name.


def _mapped_client(handler, *, voice_map=None, default_voice=None) -> Qwen3TTS:
    transport = httpx.MockTransport(handler)
    return Qwen3TTS(
        base_url="http://127.0.0.1:8112",
        speaker="Serena",
        client=httpx.AsyncClient(transport=transport),
        voice_map=voice_map,
        default_voice=default_voice,
    )


def _capturing():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, content=_tone_pcm(1000), headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE)}
        )

    return captured, handler


async def test_a_mapped_logical_voice_id_is_sent_as_its_native_speaker() -> None:
    captured, handler = _capturing()
    tts = _mapped_client(handler, voice_map={"ru_female_adult_01": "Eric"})
    stream = tts.stream(
        "тест", TtsVoiceSpec(voice_id="ru_female_adult_01", speaking_rate=1.0), request_id="r3"
    )
    _ = [chunk async for chunk in stream]

    assert captured[0]["speaker"] == "eric"  # matched case-insensitively (I8 V0)
    assert tts.native_voice_id("ru_female_adult_01") == "eric"


async def test_an_unmapped_logical_voice_id_falls_back_to_default_voice_and_never_raises() -> None:
    captured, handler = _capturing()
    tts = _mapped_client(handler, voice_map={"ru_male_adult_01": "Ryan"}, default_voice="Aiden")
    # The exact id E20-C's walk hit, and the generic provider-agnostic `SIM_TTS_VOICE_ID` default.
    for logical in ("ru_female_adult_01", "ru_female_1", "Bob"):
        stream = tts.stream(
            "тест", TtsVoiceSpec(voice_id=logical, speaking_rate=1.0), request_id=f"r-{logical}"
        )
        _ = [chunk async for chunk in stream]

    assert [body["speaker"] for body in captured] == ["aiden", "aiden", "aiden"]


async def test_an_unmapped_logical_voice_id_warns_exactly_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _captured, handler = _capturing()
    tts = _mapped_client(handler, default_voice="Serena")
    with caplog.at_level(logging.WARNING, logger="app.inference.tts.qwen3_tts"):
        for _ in range(3):
            tts.stream(
                "тест",
                TtsVoiceSpec(voice_id="ru_female_adult_01", speaking_rate=1.0),
                request_id="warn",
            )
        tts.native_voice_id("ru_female_adult_01")
        tts.stream(
            "тест", TtsVoiceSpec(voice_id="ru_male_adult_01", speaking_rate=1.0), request_id="warn2"
        )

    warnings = [r for r in caplog.records if "voice_map" in r.getMessage()]
    assert len(warnings) == 2  # once per (provider, logical id), not once per call
    assert "ru_female_adult_01" in warnings[0].getMessage()
    assert "ru_male_adult_01" in warnings[1].getMessage()


def test_a_default_voice_that_is_not_a_vendor_speaker_is_refused_at_construction() -> None:
    """A configuration error is caught once, at build time — never per utterance."""
    with pytest.raises(ValueError, match="default_voice"):
        Qwen3TTS(
            base_url="http://127.0.0.1:8112", speaker="Serena", default_voice="ru_female_adult_01"
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

    assert captured[0]["speaker"] == "serena"  # the `_client()` fixture's default speaker


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


# -- E20-I: a cold worker's first /warm_up gets the WARM-UP budget, not the per-utterance one ----


class _TimeoutRecorder(httpx.AsyncBaseTransport):
    """Records the read timeout httpx was given for each path, answers 200."""

    def __init__(self) -> None:
        self.read_timeouts: dict[str, float | None] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.read_timeouts[request.url.path] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json={"status": "ok", "loaded": True})


async def test_warm_up_uses_the_warmup_timeout_not_the_request_timeout() -> None:
    """Under `make up` a cold 1.7B warm-up took ~26 s; an 8 s per-request budget made the
    agent's first warm-up time out every time (TTS NOT_READY, E20-I)."""
    recorder = _TimeoutRecorder()
    tts = Qwen3TTS(
        base_url="http://127.0.0.1:8112",
        speaker="Serena",
        timeout_ms=8000,
        warmup_timeout_ms=60000,
        client=httpx.AsyncClient(transport=recorder),
    )
    await tts.warm_up()
    assert recorder.read_timeouts["/warm_up"] == 60.0


async def test_without_a_warmup_timeout_warm_up_keeps_the_request_timeout() -> None:
    recorder = _TimeoutRecorder()
    tts = Qwen3TTS(
        base_url="http://127.0.0.1:8112",
        speaker="Serena",
        timeout_ms=8000,
        client=httpx.AsyncClient(transport=recorder),
    )
    await tts.warm_up()
    assert recorder.read_timeouts["/warm_up"] == 8.0


# -- I8 V1: seed, tempo and what the worker reports back -------------------------------------------

#: DEV_3060TI_VOICE's table (A1-plan §2.4).
_TEMPO_TABLE = {
    "CALM": 1.10,
    "WORRIED": 1.15,
    "FRIGHTENED": 1.20,
    "PANICKED": 1.20,
    "ANGRY": 1.15,
    "CONFUSED": 1.10,
    "APATHETIC": 1.10,
    "PAIN": 1.25,
}


def _v1_client(handler, *, tempo_by_emotion: dict[str, float] | None = None) -> Qwen3TTS:
    return Qwen3TTS(
        base_url="http://127.0.0.1:8112",
        speaker="serena",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        tempo_by_emotion=tempo_by_emotion,
    )


def _v1_response(headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        content=_tone_pcm(OUTPUT_SAMPLE_RATE // 10),
        headers={"X-Sample-Rate": str(OUTPUT_SAMPLE_RATE), **(headers or {})},
    )


async def test_the_seed_and_the_emotion_tempo_are_sent() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _v1_response()

    tts = _v1_client(handler, tempo_by_emotion=_TEMPO_TABLE)
    voice = TtsVoiceSpec(
        voice_id="serena",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.PANICKED, stress_level=0.9),
        seed=987654,
    )
    [_ async for _ in tts.stream("Горит!", voice, request_id="v1")]

    assert captured[0]["seed"] == 987654
    assert captured[0]["tempo"] == 1.20


async def test_no_seed_on_the_voice_sends_no_seed_and_no_table_sends_tempo_1() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _v1_response()

    tts = _v1_client(handler)
    [_ async for _ in tts.stream("Алло.", _VOICE, request_id="v1")]

    assert "seed" not in captured[0]
    assert captured[0]["tempo"] == 1.0


def test_tempo_follows_the_table_the_voice_style_wins_and_none_emotion_is_calm() -> None:
    tts = _v1_client(lambda request: _v1_response(), tempo_by_emotion=_TEMPO_TABLE)
    worried = EmotionState(emotion=EmotionLabel.WORRIED, stress_level=0.2)

    assert tts.tempo_for(TtsVoiceSpec(voice_id="x", speaking_rate=1.0, emotion=worried)) == 1.15
    assert (
        tts.tempo_for(
            TtsVoiceSpec(
                voice_id="x",
                speaking_rate=1.0,
                emotion=worried,
                voice_style=CallerVoiceStyle.PAIN,
            )
        )
        == 1.25
    )
    assert tts.tempo_for(TtsVoiceSpec(voice_id="x", speaking_rate=1.0)) == 1.10


def test_a_table_without_a_pain_row_falls_back_to_the_emotion() -> None:
    table = {key: value for key, value in _TEMPO_TABLE.items() if key != "PAIN"}
    tts = _v1_client(lambda request: _v1_response(), tempo_by_emotion=table)
    voice = TtsVoiceSpec(
        voice_id="x",
        speaking_rate=1.0,
        emotion=EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.5),
        voice_style=CallerVoiceStyle.PAIN,
    )

    assert tts.tempo_for(voice) == 1.20


async def test_the_workers_answer_becomes_the_streams_synthesis_attributes() -> None:
    tts = _v1_client(
        lambda request: _v1_response(
            {"X-Seed": "43", "X-Tempo": "1.2", "X-QC": "regenerated", "X-Units": "1"}
        )
    )
    stream = tts.stream("Горит!", _VOICE, request_id="v1")
    [_ async for _ in stream]

    assert stream.synthesis_attributes == {
        "style_version": 2,
        "seed": 43,
        "tempo": 1.2,
        "retried": True,
    }


async def test_an_unseeded_answer_has_no_seed_and_a_multi_segment_one_reports_the_first() -> None:
    unseeded = _v1_client(
        lambda request: _v1_response({"X-Seed": "none", "X-Tempo": "1", "X-QC": "skipped"})
    )
    stream = unseeded.stream("Да.", _VOICE, request_id="v1")
    [_ async for _ in stream]
    assert stream.synthesis_attributes == {"style_version": 2, "tempo": 1.0, "retried": False}

    segmented = _v1_client(
        lambda request: _v1_response({"X-Seed": "7,8", "X-Tempo": "1.1", "X-QC": "regenerated"})
    )
    stream = segmented.stream("Длинно.", _VOICE, request_id="v2")
    [_ async for _ in stream]
    assert stream.synthesis_attributes is not None
    assert stream.synthesis_attributes["seed"] == 7


async def test_a_pre_v1_worker_reports_only_the_style_version() -> None:
    """No V1 headers -> nothing is guessed."""
    tts = _v1_client(lambda request: _v1_response())
    stream = tts.stream("Алло.", _VOICE, request_id="v1")
    [_ async for _ in stream]

    assert stream.synthesis_attributes == {"style_version": 2}
