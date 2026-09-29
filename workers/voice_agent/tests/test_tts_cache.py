"""`TtsLineCache.warm(..., qc=...)` — I8 V4's seed-retry + sidecar QC hook.

`test_service_head_in_agent.py` already covers `warm()`'s plain path (`qc=None`, unchanged since
I3 E6c); this file is only the new `CallerLineQc` behaviour: seed derivation, the retry-on-failed-
QC loop, the sidecar JSON, and "never cache a line that never passed" (`tts_cache.py`'s own
long-standing "a miss is only a miss" rule, now extended to a QC failure).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import TtsChunk, TtsVoiceSpec
from app.inference.asr.fake_asr import FakeASR
from voice_agent.tts_cache import CallerLineQc, TtsLineCache, _base_seed, line_key

LINE = "Простите, я не расслышала, повторите, пожалуйста."
_SAMPLE_RATE = 8000


class SeedSensitiveTTS:
    """A `TTSProvider` whose clip length depends on `voice.seed`: fast (rate-check pass) for the
    seeds in `good_seeds`, absurdly slow (rate-check fail) for every other seed. Deterministic and
    seedable, the two properties `FakeTTS` (§2.4) does not need but this test does."""

    provider_name = "seed-sensitive"
    model_version = "1"
    output_sample_rate = _SAMPLE_RATE

    def __init__(self, good_seeds: frozenset[int]) -> None:
        self._good_seeds = good_seeds
        self.requests: list[tuple[str, int | None]] = []

    async def warm_up(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def stream(
        self, text: str, voice: TtsVoiceSpec, *, request_id: str, max_chunk_ms: int = 20
    ) -> Any:
        self.requests.append((text, voice.seed))
        ms_per_char = 60.0 if voice.seed in self._good_seeds else 4000.0
        audio_ms = max(1, int(ms_per_char * len(text)))
        samples = max(1, self.output_sample_rate * audio_ms // 1000)
        pcm = b"\x00\x00" * samples
        rate = self.output_sample_rate

        class _Stream:
            def __aiter__(self) -> AsyncIterator[TtsChunk]:
                return self._chunks()

            async def _chunks(self) -> AsyncIterator[TtsChunk]:
                yield TtsChunk(
                    frame=AudioFrame(
                        pcm=pcm,
                        sample_rate=rate,
                        num_channels=1,
                        samples_per_channel=samples,
                        capture_offset_ms=0,
                    ),
                    text_offset_start=0,
                    text_offset_end=len(text),
                    alignment_is_exact=True,
                    chunk_index=0,
                    audio_ms=audio_ms,
                )

        return _Stream()


def _voice(voice_id: str = "ru_female_adult_01") -> TtsVoiceSpec:
    return TtsVoiceSpec(voice_id=voice_id, speaking_rate=1.0)


async def test_the_first_attempt_wins_when_its_rate_is_fine(tmp_path: Path) -> None:
    base = _base_seed("ru_female_adult_01", LINE)
    tts = SeedSensitiveTTS(good_seeds=frozenset({base}))
    cache = TtsLineCache(tmp_path)
    qc = CallerLineQc(asr=None)

    assert await cache.warm(tts, _voice(), [LINE], qc=qc) == 1
    assert cache.get("ru_female_adult_01", LINE) is not None
    assert tts.requests == [(LINE, base)]

    sidecar = cache.qc_sidecar("ru_female_adult_01", LINE)
    assert sidecar is not None
    assert sidecar["seed"] == base
    assert sidecar["attempts"] == 1
    assert sidecar["checked_cer"] is False  # no ASR was given
    assert sidecar["cer"] is None


async def test_it_retries_on_the_next_seed_until_one_passes(tmp_path: Path) -> None:
    base = _base_seed("ru_female_adult_01", LINE)
    winning_seed = base + 2
    tts = SeedSensitiveTTS(good_seeds=frozenset({winning_seed}))
    cache = TtsLineCache(tmp_path)
    qc = CallerLineQc(asr=None, max_tries=3)

    assert await cache.warm(tts, _voice(), [LINE], qc=qc) == 1
    assert tts.requests == [(LINE, base), (LINE, base + 1), (LINE, winning_seed)]

    sidecar = cache.qc_sidecar("ru_female_adult_01", LINE)
    assert sidecar is not None
    assert sidecar["seed"] == winning_seed
    assert sidecar["attempts"] == 3


async def test_a_line_that_never_passes_qc_stays_a_miss(tmp_path: Path) -> None:
    tts = SeedSensitiveTTS(good_seeds=frozenset())  # no seed is ever good
    cache = TtsLineCache(tmp_path)
    qc = CallerLineQc(asr=None, max_tries=3)

    assert await cache.warm(tts, _voice(), [LINE], qc=qc) == 0
    assert cache.get("ru_female_adult_01", LINE) is None
    assert cache.qc_sidecar("ru_female_adult_01", LINE) is None
    assert len(tts.requests) == 3  # every try was spent, then given up on


async def test_a_fake_asr_still_only_checks_the_rate(tmp_path: Path) -> None:
    """The gate's `FakeASR` never decides a cached line's fate (`tts_qc.check_clip`'s own rule)."""
    base = _base_seed("ru_female_adult_01", LINE)
    tts = SeedSensitiveTTS(good_seeds=frozenset({base}))
    cache = TtsLineCache(tmp_path)
    asr = FakeASR(["что угодно, лишь бы не совпало"])
    qc = CallerLineQc(asr=asr)

    assert await cache.warm(tts, _voice(), [LINE], qc=qc) == 1
    sidecar = cache.qc_sidecar("ru_female_adult_01", LINE)
    assert sidecar is not None
    assert sidecar["checked_cer"] is False
    assert sidecar["asr_provider"] == "fake"
    assert asr.calls == []


async def test_the_seed_is_deterministic_for_the_same_voice_and_text(tmp_path: Path) -> None:
    """A cache rebuild (a fresh process, an empty `tmp_path`) asks the model the same first
    question every time — the whole point of deriving the seed instead of drawing it at random."""
    left = tmp_path / "left"
    right = tmp_path / "right"
    base = _base_seed("ru_female_adult_01", LINE)
    qc = CallerLineQc(asr=None)

    await TtsLineCache(left).warm(
        SeedSensitiveTTS(good_seeds=frozenset({base})), _voice(), [LINE], qc=qc
    )
    await TtsLineCache(right).warm(
        SeedSensitiveTTS(good_seeds=frozenset({base})), _voice(), [LINE], qc=qc
    )

    left_sidecar = TtsLineCache(left).qc_sidecar("ru_female_adult_01", LINE)
    right_sidecar = TtsLineCache(right).qc_sidecar("ru_female_adult_01", LINE)
    assert left_sidecar is not None and right_sidecar is not None
    assert left_sidecar["seed"] == right_sidecar["seed"] == base


async def test_the_wav_and_sidecar_sit_beside_each_other_on_disk(tmp_path: Path) -> None:
    base = _base_seed("ru_female_adult_01", LINE)
    tts = SeedSensitiveTTS(good_seeds=frozenset({base}))
    cache = TtsLineCache(tmp_path)
    qc = CallerLineQc(asr=None)

    await cache.warm(tts, _voice(), [LINE], qc=qc)
    stem = line_key(LINE)
    assert (tmp_path / "ru_female_adult_01" / f"{stem}.wav").is_file()
    assert (tmp_path / "ru_female_adult_01" / f"{stem}.qc.json").is_file()


async def test_a_plain_warm_with_no_qc_writes_no_sidecar(tmp_path: Path) -> None:
    """`qc=None` (every call site before I8 V4, still what persona lines use) never seeds and
    never writes a sidecar — the exact old behaviour."""
    tts = SeedSensitiveTTS(good_seeds=frozenset({None}))  # unseeded calls pass voice.seed=None
    cache = TtsLineCache(tmp_path)

    assert await cache.warm(tts, _voice(), [LINE]) == 1
    assert tts.requests == [(LINE, None)]
    assert cache.qc_sidecar("ru_female_adult_01", LINE) is None
