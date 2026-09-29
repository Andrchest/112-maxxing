"""`voice_agent.tts_qc` — CER + rate, offline (I8 V4, I8 A1 §2.2).

`FakeASR` (D13, `app.inference.asr.fake_asr`) is what proves the "fake ASR degrades to rate-only"
rule; a tiny local stub (not `FakeASR` — its `provider_name` cannot be overridden) is what proves
the CER path actually runs against a non-fake provider.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.asr import AsrResult
from app.inference.asr.fake_asr import FakeASR
from voice_agent import tts_qc

TEXT = "Простите, я не расслышала, повторите, пожалуйста."
#: 16 ms/char keeps `chars_per_s` inside [MIN_CHARS_PER_S, MAX_CHARS_PER_S] for TEXT.
_MS_PER_CHAR = 60


def _audio_ms(text: str) -> int:
    return len(text) * _MS_PER_CHAR


@dataclass(frozen=True, slots=True)
class _StubAsr:
    """A minimal `AsrPort` whose `provider_name` a test controls (`FakeASR`'s is fixed to
    `"fake"`, which is exactly the branch this double exists to test *around*)."""

    provider_name: str
    text: str

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        return AsrResult(
            text=self.text,
            is_final=True,
            start_ms=0,
            end_ms=0,
            confidence=1.0,
            provider=self.provider_name,
        )


# -- normalize_for_cer -----------------------------------------------------------------------


def test_normalize_lower_cases_strips_punctuation_and_folds_yo() -> None:
    assert tts_qc.normalize_for_cer("Ёлка,  дом!") == "елка дом"


def test_normalize_spells_out_digits_as_words() -> None:
    assert tts_qc.normalize_for_cer("Дом 27.") == "дом двадцать семь"
    assert tts_qc.normalize_for_cer("2026 год") == "две тысячи двадцать шесть год"


def test_normalize_collapses_whitespace() -> None:
    assert tts_qc.normalize_for_cer("  a   b  ") == "a b"


# -- character_error_rate --------------------------------------------------------------------


def test_cer_of_identical_text_is_zero() -> None:
    assert tts_qc.character_error_rate(TEXT, TEXT) == 0.0


def test_cer_is_symmetric_to_case_and_punctuation() -> None:
    assert tts_qc.character_error_rate(TEXT, TEXT.upper().replace(",", "")) == 0.0


def test_cer_of_a_wrong_transcript_is_positive() -> None:
    assert tts_qc.character_error_rate(TEXT, "совсем другой текст") > 0.5


def test_cer_of_an_empty_reference() -> None:
    assert tts_qc.character_error_rate("   ", "") == 0.0
    assert tts_qc.character_error_rate("   ", "что-то") == 1.0


# -- rate -------------------------------------------------------------------------------------


def test_spoken_chars_counts_letters_and_digits_only() -> None:
    assert tts_qc.spoken_chars("Дом 27, кв. 3!") == len("Дом27кв3")


def test_rate_ok_bounds() -> None:
    assert tts_qc.rate_ok(TEXT, _audio_ms(TEXT))
    assert not tts_qc.rate_ok(TEXT, 1)  # way too fast (truncated)
    assert not tts_qc.rate_ok(TEXT, _audio_ms(TEXT) * 100)  # way too slow (runaway)


# -- check_clip ---------------------------------------------------------------------------------


async def test_check_clip_with_no_asr_is_rate_only() -> None:
    outcome = await tts_qc.check_clip(
        text=TEXT,
        pcm=b"",
        sample_rate=24000,
        audio_ms=_audio_ms(TEXT),
        asr=None,
        request_id="r1",
    )
    assert outcome.passed
    assert outcome.checked_cer is False
    assert outcome.cer is None
    assert outcome.asr_provider is None


async def test_check_clip_with_a_fake_asr_is_also_rate_only() -> None:
    """The gate's `FakeASR` would make CER pass or fail by test-script fiat, never by anything
    the clip's own audio said — `check_clip` never lets it decide a caller line's fate."""
    asr = FakeASR(["что угодно совсем другое"])
    outcome = await tts_qc.check_clip(
        text=TEXT,
        pcm=b"",
        sample_rate=24000,
        audio_ms=_audio_ms(TEXT),
        asr=asr,
        request_id="r1",
    )
    assert outcome.passed
    assert outcome.checked_cer is False
    assert outcome.cer is None
    assert outcome.asr_provider == "fake"
    assert asr.calls == []  # never even asked to transcribe


async def test_check_clip_runs_cer_against_a_real_provider() -> None:
    asr = _StubAsr(provider_name="gigaam", text=TEXT)
    outcome = await tts_qc.check_clip(
        text=TEXT,
        pcm=b"\x00\x00",
        sample_rate=24000,
        audio_ms=_audio_ms(TEXT),
        asr=asr,
        request_id="r1",
    )
    assert outcome.passed
    assert outcome.checked_cer is True
    assert outcome.cer == 0.0
    assert outcome.asr_provider == "gigaam"


async def test_check_clip_fails_on_a_high_cer() -> None:
    asr = _StubAsr(provider_name="gigaam", text="абсолютно не то, что было сказано")
    outcome = await tts_qc.check_clip(
        text=TEXT,
        pcm=b"\x00\x00",
        sample_rate=24000,
        audio_ms=_audio_ms(TEXT),
        asr=asr,
        request_id="r1",
    )
    assert not outcome.passed
    assert outcome.reason == "cer"
    assert outcome.cer is not None and outcome.cer > tts_qc.CER_THRESHOLD


async def test_check_clip_fails_on_rate_even_with_a_perfect_transcript() -> None:
    asr = _StubAsr(provider_name="gigaam", text=TEXT)
    outcome = await tts_qc.check_clip(
        text=TEXT,
        pcm=b"\x00\x00",
        sample_rate=24000,
        audio_ms=1,
        asr=asr,
        request_id="r1",
    )
    assert not outcome.passed
    assert outcome.reason == "rate"
    assert outcome.cer == 0.0  # CER still ran and still reports its own (unrelated) number
