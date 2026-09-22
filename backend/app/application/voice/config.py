"""`VoiceTurnConfig` — every tunable of the turn path (HLD `50-voice-pipeline.md` §4.1, D9).

SPEC §17 is explicit: "Make this configuration, not a hard-coded magic value." So the thresholds,
the sustain windows, the endpoint silence, the pre-roll and the queue depths all live here, are
loaded from `Settings` — overlaid by the active model profile's `voice_turn.*` block before this
function ever sees it (`app.config.profile.apply_profile`, E18-A, HLD `60-inference-ops.md` §2) —
and the `TurnDetector` reads them off this object. A unit test enforces the other half of that
sentence: `turn_detector.py` contains no numeric literal other than `0` and `1`.

Validation at load is §4.1's list, verbatim:

* `speech_end_threshold <= speech_start_threshold` (the hysteresis band cannot be inverted);
* `speech_start_min_ms`, `barge_in_min_speech_ms` and `endpoint_silence_ms` are integer multiples
  of `vad_frame_ms` — "rounded up at load with a warning if not", because a sustain window that
  is not a whole number of analysis frames is a window the detector can never measure exactly;
* `min_turn_ms < max_turn_ms`;
* `tts_chunk_ms <= outbound_queue_ms` (a chunk larger than the queue could never be buffered).

The ranges are `Field` bounds, so an out-of-range value is a `ValidationError` at load and never a
silently clamped pipeline. `endpoint_silence_ms` carries both of §4.1's bounds: the hard bound
150–1500 is the `Field` constraint, and SPEC §17's initial target band 250–350 is checked
separately and *warned* about rather than refused, because §4.1 calls it the initial target and
this task's parametrised endpoint tests deliberately sweep it.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:  # pragma: no cover - import cycle guard only
    from app.config.settings import Settings

__all__ = [
    "BYTES_PER_SAMPLE",
    "ENDPOINT_SILENCE_TARGET_MAX_MS",
    "ENDPOINT_SILENCE_TARGET_MIN_MS",
    "MS_PER_S",
    "VoiceTurnConfig",
    "voice_turn_config_from_settings",
]

logger = logging.getLogger(__name__)

#: Bytes per sample of the s16le format every stage after the `Resampler` uses (§3.1, §9.1).
BYTES_PER_SAMPLE = 2
#: Milliseconds in a second. Named so that the turn detector can convert bytes to milliseconds
#: without a numeric literal of its own (SPEC §17: configuration, never a magic value).
MS_PER_S = 1000

#: SPEC §17's initial target band for `endpoint_silence_ms`; outside it the config still loads
#: (the hard bound is 150–1500) but the mismatch with the SPEC target is logged.
ENDPOINT_SILENCE_TARGET_MIN_MS = 250
ENDPOINT_SILENCE_TARGET_MAX_MS = 350

#: §4.4 finalization: how much of the trailing endpoint silence survives the trim, so ASR keeps
#: the final consonant but not the whole pause.
_TRAILING_PAD_MS_DEFAULT = 100

_MULTIPLE_OF_FRAME = ("speech_start_min_ms", "barge_in_min_speech_ms", "endpoint_silence_ms")


class VoiceTurnConfig(BaseModel):
    """§4.1's table, as a frozen value object. Defaults and ranges are the HLD's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    speech_start_threshold: float = Field(default=0.55, ge=0.30, le=0.90)
    """VAD probability at or above which a frame counts as speech."""

    speech_end_threshold: float = Field(default=0.35, ge=0.10, le=0.90)
    """Probability below which a frame counts as silence (hysteresis)."""

    speech_start_min_ms: int = Field(default=96, ge=32, le=400)
    """Consecutive speech needed to leave PRE_SPEECH on a cold turn start."""

    endpoint_silence_ms: int = Field(default=300, ge=150, le=1500)
    """Trailing silence that finalizes a turn (SPEC §17 target 250–350)."""

    pre_roll_ms: int = Field(default=300, ge=100, le=1000)
    """Audio kept before speech onset so word beginnings survive."""

    barge_in_min_speech_ms: int = Field(default=120, ge=60, le=400)
    """Sustained speech during playback before a barge-in fires (SPEC §18 step 1)."""

    max_turn_ms: int = Field(default=30_000, ge=5_000, le=120_000)
    """Hard cap; forces `end_reason = MAX_TURN_MS`."""

    min_turn_ms: int = Field(default=200, ge=0, le=2_000)
    """Turns shorter than this are discarded as noise, no ASR."""

    vad_frame_ms: int = Field(default=32, ge=1, le=100)
    """Analysis frame length, fixed by `VADProvider.frame_samples`."""

    trailing_pad_ms: int = Field(default=_TRAILING_PAD_MS_DEFAULT, ge=0, le=500)
    """§4.4: the kept part of the trimmed trailing silence."""

    outbound_queue_ms: int = Field(default=200, ge=40, le=500)
    """Transport outbound buffer depth (`queue_size_ms`)."""

    tts_chunk_ms: int = Field(default=20, ge=10, le=60)
    """`max_chunk_ms` handed to `TTSProvider.stream` (E14)."""

    partial_asr_enabled: bool = True
    """Whether `ASR_PARTIAL` is produced at all (also gated per session by `SessionPolicy`, D6)."""

    partial_interval_ms: int = Field(default=500, ge=200, le=2_000)
    """Pseudo-streaming partial cadence (§4.5, E12)."""

    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    """The rate the `Resampler` produces and every downstream stage assumes (§3.1, §9.1)."""

    reconnect_grace_s: int = Field(default=30, ge=0, le=600)
    """ADDITIVE (E18-A, R6): HLD 60 §6 row 5 / SPEC §39 item 5. A LiveKit disconnect longer than
    this ends the call (`CALL_ENDED{reason:"TRANSPORT_LOST"}`); the timer that reads it lives in
    the application pipeline (E18-C), not here — this object only carries the configured number."""

    @model_validator(mode="before")
    @classmethod
    def _round_sustain_windows_up(cls, data: Any) -> Any:
        """Round the three frame-quantised windows up to whole frames, with a warning (§4.1)."""
        if not isinstance(data, dict):
            return data
        frame_ms = data.get("vad_frame_ms", cls.model_fields["vad_frame_ms"].default)
        if not isinstance(frame_ms, int) or frame_ms <= 0:
            return data
        rounded = dict(data)
        for key in _MULTIPLE_OF_FRAME:
            value = rounded.get(key, cls.model_fields[key].default)
            if not isinstance(value, int) or value % frame_ms == 0:
                continue
            up = math.ceil(value / frame_ms) * frame_ms
            logger.warning(
                "%s=%d is not a multiple of vad_frame_ms=%d; rounded up to %d (HLD 50 §4.1)",
                key,
                value,
                frame_ms,
                up,
            )
            rounded[key] = up
        return rounded

    @model_validator(mode="after")
    def _check_relations(self) -> VoiceTurnConfig:
        """§4.1's cross-field validation."""
        if self.speech_end_threshold > self.speech_start_threshold:
            raise ValueError(
                "speech_end_threshold must not exceed speech_start_threshold "
                f"({self.speech_end_threshold} > {self.speech_start_threshold})"
            )
        if self.min_turn_ms >= self.max_turn_ms:
            raise ValueError(
                f"min_turn_ms must be below max_turn_ms ({self.min_turn_ms} >= {self.max_turn_ms})"
            )
        if self.tts_chunk_ms > self.outbound_queue_ms:
            raise ValueError(
                "tts_chunk_ms must not exceed outbound_queue_ms "
                f"({self.tts_chunk_ms} > {self.outbound_queue_ms})"
            )
        if not (
            ENDPOINT_SILENCE_TARGET_MIN_MS
            <= self.endpoint_silence_ms
            <= ENDPOINT_SILENCE_TARGET_MAX_MS
        ):
            logger.warning(
                "endpoint_silence_ms=%d is outside SPEC §17's initial target band %d–%d",
                self.endpoint_silence_ms,
                ENDPOINT_SILENCE_TARGET_MIN_MS,
                ENDPOINT_SILENCE_TARGET_MAX_MS,
            )
        return self

    @property
    def pre_roll_frames(self) -> int:
        """`ceil(pre_roll_ms / vad_frame_ms)` — the `PreRollBuffer` capacity (§4.2)."""
        return math.ceil(self.pre_roll_ms / self.vad_frame_ms)

    @property
    def frame_samples(self) -> int:
        """Samples per analysis frame at `sample_rate` — what the `Resampler` re-blocks to."""
        return (self.sample_rate * self.vad_frame_ms) // MS_PER_S

    @property
    def bytes_per_ms(self) -> float:
        """Bytes of mono s16le audio per millisecond at `sample_rate`."""
        return self.sample_rate * BYTES_PER_SAMPLE / MS_PER_S


def voice_turn_config_from_settings(settings: Settings) -> VoiceTurnConfig:
    """Build the config from the `SIM_VOICE_*` environment block (§4.1, D9).

    The active model profile's `voice_turn.*` block (HLD `60-inference-ops.md` §2) has already
    overlaid these `Settings` fields by the time a caller reaches this function
    (`app.config.profile.apply_profile`, called once at process start-up, E18-A) — this function
    itself needs no profile awareness; the env block stays the source for a process with no
    profile loaded (e.g. a unit test building `Settings` directly).
    """
    return VoiceTurnConfig(
        speech_start_threshold=settings.voice_speech_start_threshold,
        speech_end_threshold=settings.voice_speech_end_threshold,
        speech_start_min_ms=settings.voice_speech_start_min_ms,
        endpoint_silence_ms=settings.voice_endpoint_silence_ms,
        pre_roll_ms=settings.voice_pre_roll_ms,
        barge_in_min_speech_ms=settings.voice_barge_in_min_speech_ms,
        max_turn_ms=settings.voice_max_turn_ms,
        min_turn_ms=settings.voice_min_turn_ms,
        vad_frame_ms=settings.voice_vad_frame_ms,
        trailing_pad_ms=settings.voice_trailing_pad_ms,
        outbound_queue_ms=settings.voice_outbound_queue_ms,
        tts_chunk_ms=settings.voice_tts_chunk_ms,
        partial_asr_enabled=settings.voice_partial_asr_enabled,
        partial_interval_ms=settings.voice_partial_interval_ms,
        sample_rate=settings.voice_sample_rate,
        reconnect_grace_s=settings.voice_reconnect_grace_s,
    )
