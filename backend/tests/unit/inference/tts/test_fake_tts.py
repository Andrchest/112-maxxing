"""`FakeTTS` — the gate's `TTSProvider` (HLD `50-voice-pipeline.md` §2.4, D13).

A fake is only useful if it is *exactly* reproducible: every barge-in and latency assertion in
this epic computes its expected numbers from the length function pinned here.
"""

from __future__ import annotations

import pytest
from app.application.ports.tts import TTSProvider, TtsUnavailableError, TtsVoiceSpec
from app.inference.tts.fake_tts import DEFAULT_MS_PER_CHAR, FakeTTS

VOICE = TtsVoiceSpec(voice_id="ru_female_1", speaking_rate=1.0)
TEXT_RU = "Алло, я вас слушаю."


async def drain(provider: FakeTTS, text: str, *, max_chunk_ms: int = 40) -> list[object]:
    stream = provider.stream(text, VOICE, request_id="r", max_chunk_ms=max_chunk_ms)
    return [chunk async for chunk in stream]


def test_it_satisfies_the_port() -> None:
    """The gate runs against the Protocol, not against this class (D2)."""
    assert isinstance(FakeTTS(), TTSProvider)


def test_the_length_function_is_the_documented_one() -> None:
    """60 ms per character, rounded up to a whole `max_chunk_ms` frame."""
    provider = FakeTTS()

    assert provider.ms_per_char == DEFAULT_MS_PER_CHAR == 60.0
    assert provider.audio_ms_for("abc", max_chunk_ms=40) == 200  # 180 → 5 frames of 40
    assert provider.audio_ms_for("", max_chunk_ms=40) == 0


async def test_the_same_request_produces_byte_identical_frames() -> None:
    """Determinism: a recording assertion must not depend on when the test ran."""
    first = await drain(FakeTTS(), TEXT_RU)
    second = await drain(FakeTTS(), TEXT_RU)

    assert [chunk.frame.pcm for chunk in first] == [chunk.frame.pcm for chunk in second]
    assert [chunk.audio_ms for chunk in first] == [chunk.audio_ms for chunk in second]
    assert [chunk.text_offset_end for chunk in first] == [c.text_offset_end for c in second]


async def test_chunks_never_exceed_max_chunk_ms_and_cover_the_whole_text() -> None:
    """§2.4: bounded cancellation granularity, and exact alignment that reaches `len(text)`."""
    chunks = await drain(FakeTTS(), TEXT_RU, max_chunk_ms=40)

    assert chunks
    assert all(chunk.audio_ms <= 40 for chunk in chunks)
    assert all(chunk.alignment_is_exact for chunk in chunks)
    assert chunks[0].text_offset_start == 0
    assert chunks[-1].text_offset_end == len(TEXT_RU)
    assert sum(chunk.audio_ms for chunk in chunks) == FakeTTS().audio_ms_for(
        TEXT_RU, max_chunk_ms=40
    )


async def test_offsets_are_monotonic() -> None:
    """A later chunk never covers earlier text — `delivered_text` is a prefix (§6.3)."""
    chunks = await drain(FakeTTS(), TEXT_RU)

    ends = [chunk.text_offset_end for chunk in chunks]
    assert ends == sorted(ends)


async def test_every_frame_is_a_whole_mono_s16le_block() -> None:
    """`len(pcm) == samples_per_channel * num_channels * 2` (§2.1's `AudioFrame`)."""
    chunks = await drain(FakeTTS(), TEXT_RU)

    for chunk in chunks:
        frame = chunk.frame
        assert len(frame.pcm) == frame.samples_per_channel * frame.num_channels * 2
        assert frame.num_channels == 1
        assert frame.sample_rate == 16_000


async def test_silence_by_default_and_a_tone_on_request() -> None:
    """Two deterministic waveforms; a recording test needs to tell audio from padding."""
    silent = await drain(FakeTTS(), TEXT_RU)
    tonal = await drain(FakeTTS(tone_hz=440.0), TEXT_RU)

    assert all(chunk.frame.pcm == b"\x00" * len(chunk.frame.pcm) for chunk in silent)
    assert any(chunk.frame.pcm != b"\x00" * len(chunk.frame.pcm) for chunk in tonal)


async def test_an_empty_text_produces_no_audio() -> None:
    assert await drain(FakeTTS(), "") == []


async def test_warm_up_can_be_scripted_to_fail() -> None:
    """§4.2's warm-up failure path, with no model to break."""
    provider = FakeTTS(fail_on_warm_up=TtsUnavailableError("no weights"))

    with pytest.raises(TtsUnavailableError):
        await provider.warm_up()
    assert provider.warm_ups == 0

    healthy = FakeTTS()
    await healthy.warm_up()
    assert healthy.warm_ups == 1


async def test_a_scripted_failure_raises_instead_of_the_nth_chunk() -> None:
    """INV 14's TTS variant, mid-utterance rather than at the first byte."""
    provider = FakeTTS(fail_on_chunk=2)
    stream = provider.stream(TEXT_RU, VOICE, request_id="r", max_chunk_ms=40)

    seen = []
    with pytest.raises(TtsUnavailableError):
        async for chunk in stream:
            seen.append(chunk)

    assert len(seen) == 2


async def test_cancel_stops_iteration_promptly() -> None:
    """§2.4: "stop generation as soon as the current chunk completes"."""
    provider = FakeTTS()
    stream = provider.stream(TEXT_RU, VOICE, request_id="r", max_chunk_ms=40)

    seen = []
    async for chunk in stream:
        seen.append(chunk)
        await stream.cancel()

    assert len(seen) == 1
    assert stream.cancelled is True


async def test_the_stream_reports_its_request_id_and_text() -> None:
    provider = FakeTTS()
    stream = provider.stream(TEXT_RU, VOICE, request_id="turn-1:tts")

    assert stream.request_id == "turn-1:tts"
    assert stream.text == TEXT_RU
    assert provider.requests == [(TEXT_RU, VOICE, "turn-1:tts")]


def test_the_constructor_refuses_a_nonsense_configuration() -> None:
    with pytest.raises(ValueError, match="output_sample_rate"):
        FakeTTS(output_sample_rate=0)
    with pytest.raises(ValueError, match="ms_per_char"):
        FakeTTS(ms_per_char=0.0)
