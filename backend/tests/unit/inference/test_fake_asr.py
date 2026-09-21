"""`FakeASR` — determinism and port conformance (D13, HLD `50-voice-pipeline.md` §2.3).

`FakeASR` is the provider `make gate` runs against, which makes its own determinism a property
the whole suite rests on: if the fake varied, every test above it would inherit the variation.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from app.application.ports.asr import AsrPartial, ASRProvider, AsrResult
from app.application.ports.call_transport import AudioFrame
from app.application.testing.fakes import sine_burst_frames
from app.inference.asr import FakeASR
from app.inference.asr.fake_asr import partial_prefixes

SAMPLE_RATE = 16_000
#: Half a second of 16 kHz mono s16le.
AUDIO = b"\x01\x00" * (SAMPLE_RATE // 2)
TEXT_RU = "У нас пожар в доме"


def frames(duration_ms: int = 128) -> list[AudioFrame]:
    return sine_burst_frames(duration_ms=duration_ms, frame_samples=512, sample_rate=SAMPLE_RATE)


async def iterate(items: Sequence[AudioFrame]) -> AsyncIterator[AudioFrame]:
    for item in items:
        yield item


def test_fake_asr_is_an_asr_provider() -> None:
    """Port conformance: the gate's provider satisfies the protocol it is injected as."""
    assert isinstance(FakeASR(), ASRProvider)


def test_the_identity_is_fixed() -> None:
    """`provider_name` / `model_version` are what `ASR_FINAL` and the metric row carry."""
    asr = FakeASR()
    assert asr.provider_name == "fake"
    assert asr.model_version == "fake-1"
    assert asr.supports_streaming is True
    assert asr.required_sample_rate == SAMPLE_RATE


async def test_transcribe_returns_the_script_in_order() -> None:
    """Scripted finals come back one per call, in order."""
    asr = FakeASR(["первый", "второй"])
    first = await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="a")
    second = await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="b")

    assert (first.text, second.text) == ("первый", "второй")
    assert first.is_final and second.is_final
    assert first.confidence == 0.9
    assert first.provider == "fake"
    assert first.model_version == "fake-1"
    assert first.language == "ru"
    assert first.audio_duration_ms == 500
    assert first.end_ms == 500


async def test_two_identical_providers_produce_identical_output() -> None:
    """Determinism: no randomness, no clock — the same script gives the same bytes twice."""
    one = await FakeASR([TEXT_RU]).transcribe(AUDIO, SAMPLE_RATE, request_id="r")
    two = await FakeASR([TEXT_RU]).transcribe(AUDIO, SAMPLE_RATE, request_id="r")
    assert one == two


async def test_an_exhausted_script_yields_the_empty_transcript() -> None:
    """Past the end of the script the provider is silent, not broken."""
    asr = FakeASR(["один"])
    await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="a")
    beyond = await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="b")
    assert beyond.text == ""
    assert asr.remaining == 0


async def test_a_scripted_exception_is_raised_from_transcribe() -> None:
    """An `Exception` instance in the script is how a test manufactures a model failure."""
    boom = RuntimeError("the model fell over")
    asr = FakeASR([boom])
    with pytest.raises(RuntimeError, match="the model fell over"):
        await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="a")


async def test_a_scripted_exception_is_raised_from_stream() -> None:
    """The same script drives `stream()`; the two share one cursor."""
    asr = FakeASR([ValueError("no audio")])
    with pytest.raises(ValueError, match="no audio"):
        async for _ in asr.stream(iterate(frames()), request_id="s"):
            pass


async def test_every_call_is_recorded_with_its_audio_length_and_request_id() -> None:
    """`calls` is what a test asserts the pipeline actually asked for."""
    asr = FakeASR(["раз"])
    await asr.transcribe(AUDIO, SAMPLE_RATE, request_id="turn:p0")

    assert len(asr.calls) == 1
    call = asr.calls[0]
    assert call.kind == "transcribe"
    assert call.audio_bytes == len(AUDIO)
    assert call.sample_rate == SAMPLE_RATE
    assert call.request_id == "turn:p0"


async def test_stream_yields_word_prefixes_then_exactly_one_final() -> None:
    """§2.3: zero or more `AsrPartial`, then exactly one `AsrResult` with `is_final=True`."""
    asr = FakeASR([TEXT_RU])
    items = [item async for item in asr.stream(iterate(frames()), request_id="s")]

    partials = [item for item in items if isinstance(item, AsrPartial)]
    finals = [item for item in items if isinstance(item, AsrResult)]
    assert [item.text for item in partials] == [
        "У",
        "У нас",
        "У нас пожар",
        "У нас пожар в",
    ]
    assert len(finals) == 1
    assert finals[0].text == TEXT_RU
    assert all(item.stability is None for item in partials)


async def test_partials_can_be_switched_off() -> None:
    """`partials=False` streams the final alone — the non-streaming provider's shape."""
    asr = FakeASR([TEXT_RU], partials=False)
    items = [item async for item in asr.stream(iterate(frames()), request_id="s")]
    assert [type(item) for item in items] == [AsrResult]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("одно", []),
        ("два слова", ["два"]),
        ("а б в", ["а", "а б"]),
    ],
)
def test_partial_prefixes_stop_at_word_boundaries(text: str, expected: list[str]) -> None:
    """A partial is what a recogniser would have committed, and none commits half a word."""
    assert partial_prefixes(text) == expected


async def test_warm_up_and_close_are_counted_and_idempotent() -> None:
    """Warm-up consumes no script entry; `close` is idempotent (§2.3)."""
    asr = FakeASR(["раз"])
    await asr.warm_up()
    await asr.warm_up()
    await asr.close()
    await asr.close()

    assert asr.warm_ups == 2
    assert asr.closed is True
    assert asr.remaining == 1
    assert (await asr.transcribe(AUDIO, SAMPLE_RATE, request_id=str(uuid.uuid4()))).text == "раз"
