"""`TurnDetector` — the IDLE/PRE_SPEECH/IN_SPEECH/ENDPOINTING machine of §4 (D9, SPEC §17, §18).

It decides, from `VadFrameResult` probabilities only, when the trainee started and stopped
speaking and whether a barge-in occurred. It never sees text, never calls a model and never
touches the transport; the `TurnPipeline` feeds it frames and reads its signals.

**Every threshold, window and duration comes from `VoiceTurnConfig`.** SPEC §17 says so in as many
words — "Make this configuration, not a hard-coded magic value" — and
`backend/tests/unit/application/voice/test_turn_detector_no_literals.py` enforces it with an
`ast` scan: this module contains no numeric literal other than `0` and `1`. That is why the
byte/millisecond conversions go through `BYTES_PER_SAMPLE` and `MS_PER_S` imported from
`config.py` rather than being written inline.

The barge-in branch is a **flag**, not a fifth state (§4.3): entering PRE_SPEECH while playback is
active sets `was_during_playback` and swaps the sustain threshold from `speech_start_min_ms` to
the shorter `barge_in_min_speech_ms`, because SPEC §18 step 1 requires a barge-in to be confirmed
faster than a cold turn start.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from app.application.ports.call_transport import AudioFrame
from app.application.ports.vad import VadFrameResult
from app.application.voice.config import BYTES_PER_SAMPLE, MS_PER_S, VoiceTurnConfig
from app.application.voice.pre_roll import PreRollBuffer

__all__ = [
    "DetectedTurn",
    "DetectorStep",
    "SpeechStarted",
    "TurnDetector",
    "TurnDetectorState",
    "TurnEndReason",
]


class TurnDetectorState(str, Enum):
    """§4.3's four states."""

    IDLE = "IDLE"
    """No speech; frames go only to the pre-roll buffer."""

    PRE_SPEECH = "PRE_SPEECH"
    """Speech probability above the start threshold, not yet sustained."""

    IN_SPEECH = "IN_SPEECH"
    """The turn is open, frames accumulate."""

    ENDPOINTING = "ENDPOINTING"
    """Trailing silence is being counted; frames still accumulate."""


class TurnEndReason(str, Enum):
    """Why a turn finalized (§3.2's `USER_SPEECH_ENDED.end_reason`)."""

    ENDPOINT_SILENCE = "ENDPOINT_SILENCE"
    MAX_TURN_MS = "MAX_TURN_MS"
    TRANSPORT_CLOSED = "TRANSPORT_CLOSED"


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    """The IDLE/PRE_SPEECH → IN_SPEECH boundary signal (§3.2)."""

    turn_id: uuid.UUID
    turn_index: int
    start_ms: int
    """`capture_offset_ms - pre_roll_ms`, clamped at 0 (§4.4)."""

    was_during_playback: bool
    """True when the caller was speaking at onset — this turn is a barge-in (§6.1)."""


@dataclass(frozen=True, slots=True)
class DetectedTurn:
    """One finalized trainee turn (§3.2). `audio` is 16 kHz mono s16le including the pre-roll."""

    turn_id: uuid.UUID
    turn_index: int
    audio: bytes
    start_ms: int
    end_ms: int
    is_barge_in: bool
    pre_roll_ms: int
    end_reason: TurnEndReason
    discarded_short: bool
    """True when the turn is below `min_turn_ms`: logged, never transcribed (§4.4)."""

    @property
    def duration_ms(self) -> int:
        """`end_ms - start_ms`, the kept audio including the pre-roll."""
        return self.end_ms - self.start_ms


@dataclass(frozen=True, slots=True)
class DetectorStep:
    """What one frame produced: a start signal, a finalized turn, both, or neither."""

    started: SpeechStarted | None = None
    finished: DetectedTurn | None = None


class TurnDetector:
    """§4's transition table, verbatim. One instance per call."""

    def __init__(self, config: VoiceTurnConfig) -> None:
        self._config = config
        self._pre_roll = PreRollBuffer(config.pre_roll_frames)
        self._state = TurnDetectorState.IDLE
        self._speech_run_ms = 0
        self._silence_run_ms = 0
        self._sustain_ms = config.speech_start_min_ms
        self._was_during_playback = False
        self._turn_id: uuid.UUID | None = None
        self._turn_index = 0
        self._next_turn_index = 0
        self._start_ms = 0
        self._accumulator: list[bytes] = []
        self._accumulated_bytes = 0

    @property
    def state(self) -> TurnDetectorState:
        """The current state."""
        return self._state

    @property
    def config(self) -> VoiceTurnConfig:
        """The configuration every decision is read from."""
        return self._config

    @property
    def turn_open(self) -> bool:
        """True while a turn is accumulating (IN_SPEECH or ENDPOINTING)."""
        return self._turn_id is not None

    def reset(self) -> None:
        """Return to IDLE and drop every buffer. Called at the start of a call."""
        self._pre_roll.clear()
        self._state = TurnDetectorState.IDLE
        self._speech_run_ms = 0
        self._silence_run_ms = 0
        self._was_during_playback = False
        self._turn_id = None
        self._start_ms = 0
        self._accumulator = []
        self._accumulated_bytes = 0

    def process(
        self, frame: AudioFrame, result: VadFrameResult, *, playback_active: bool = False
    ) -> DetectorStep:
        """Advance the machine by one analysed frame (§4.4)."""
        config = self._config
        speech = result.speech_probability >= config.speech_start_threshold
        silence = result.speech_probability < config.speech_end_threshold

        if self._state is TurnDetectorState.IDLE:
            return self._from_idle(frame, speech, playback_active=playback_active)
        if self._state is TurnDetectorState.PRE_SPEECH:
            return self._from_pre_speech(frame, speech)
        if self._state is TurnDetectorState.IN_SPEECH:
            return self._from_in_speech(frame, silence)
        return self._from_endpointing(frame, speech, silence)

    def close(self) -> DetectorStep:
        """The "any | transport closed" row: finalize an open turn, otherwise do nothing."""
        if not self.turn_open:
            self._state = TurnDetectorState.IDLE
            return DetectorStep()
        return DetectorStep(finished=self._finalize(TurnEndReason.TRANSPORT_CLOSED))

    # -- the transition table -----------------------------------------------------------------

    def _from_idle(self, frame: AudioFrame, speech: bool, *, playback_active: bool) -> DetectorStep:
        config = self._config
        if speech:
            self._state = TurnDetectorState.PRE_SPEECH
            self._speech_run_ms = config.vad_frame_ms
            self._was_during_playback = playback_active
            self._sustain_ms = (
                config.barge_in_min_speech_ms if playback_active else config.speech_start_min_ms
            )
            # The onset frame itself stays in the pre-roll: if the run is sustained it is copied
            # into the accumulator with the rest of the buffer, and if it is not, it is just
            # another buffered frame. Either way it is never counted twice.
            self._pre_roll.push(frame)
            return DetectorStep()
        self._pre_roll.push(frame)
        return DetectorStep()

    def _from_pre_speech(self, frame: AudioFrame, speech: bool) -> DetectorStep:
        config = self._config
        if not speech:
            self._state = TurnDetectorState.IDLE
            self._speech_run_ms = 0
            self._pre_roll.push(frame)
            return DetectorStep()
        if self._speech_run_ms + config.vad_frame_ms >= self._sustain_ms:
            return DetectorStep(started=self._open_turn(frame))
        self._speech_run_ms += config.vad_frame_ms
        self._pre_roll.push(frame)
        return DetectorStep()

    def _from_in_speech(self, frame: AudioFrame, silence: bool) -> DetectorStep:
        config = self._config
        if silence:
            self._state = TurnDetectorState.ENDPOINTING
            self._silence_run_ms = config.vad_frame_ms
            self._accumulate(frame)
            return DetectorStep()
        if self._accumulated_ms() >= config.max_turn_ms:
            return DetectorStep(finished=self._finalize(TurnEndReason.MAX_TURN_MS))
        self._accumulate(frame)
        return DetectorStep()

    def _from_endpointing(self, frame: AudioFrame, speech: bool, silence: bool) -> DetectorStep:
        config = self._config
        if speech:
            self._state = TurnDetectorState.IN_SPEECH
            self._silence_run_ms = 0
            self._accumulate(frame)
            return DetectorStep()
        if silence and self._silence_run_ms + config.vad_frame_ms >= config.endpoint_silence_ms:
            self._silence_run_ms += config.vad_frame_ms
            self._accumulate(frame)
            return DetectorStep(finished=self._finalize(TurnEndReason.ENDPOINT_SILENCE))
        if silence:
            self._silence_run_ms += config.vad_frame_ms
        # A probability inside the hysteresis band extends neither run counter, but the frame is
        # still part of the turn (§4.3: "ENDPOINTING — frames still accumulate").
        self._accumulate(frame)
        return DetectorStep()

    # -- turn lifecycle -----------------------------------------------------------------------

    def _open_turn(self, frame: AudioFrame) -> SpeechStarted:
        config = self._config
        self._state = TurnDetectorState.IN_SPEECH
        self._silence_run_ms = 0
        self._turn_id = uuid.uuid4()
        self._turn_index = self._next_turn_index
        self._next_turn_index += 1
        self._start_ms = max(0, frame.capture_offset_ms - config.pre_roll_ms)
        self._accumulator = [self._pre_roll.pcm(), frame.pcm]
        self._accumulated_bytes = sum(len(chunk) for chunk in self._accumulator)
        return SpeechStarted(
            turn_id=self._turn_id,
            turn_index=self._turn_index,
            start_ms=self._start_ms,
            was_during_playback=self._was_during_playback,
        )

    def _accumulate(self, frame: AudioFrame) -> None:
        self._accumulator.append(frame.pcm)
        self._accumulated_bytes += len(frame.pcm)

    def _accumulated_ms(self) -> int:
        return self._bytes_to_ms(self._accumulated_bytes)

    def _bytes_to_ms(self, size: int) -> int:
        config = self._config
        return (size * MS_PER_S) // (config.sample_rate * BYTES_PER_SAMPLE)

    def _ms_to_bytes(self, milliseconds: int) -> int:
        config = self._config
        return (milliseconds * config.sample_rate * BYTES_PER_SAMPLE) // MS_PER_S

    def _finalize(self, end_reason: TurnEndReason) -> DetectedTurn:
        config = self._config
        turn_id = self._turn_id
        if turn_id is None:  # pragma: no cover - guarded by every caller
            raise RuntimeError("no turn is open")
        audio = b"".join(self._accumulator)
        if end_reason is TurnEndReason.ENDPOINT_SILENCE:
            trim_ms = max(0, config.endpoint_silence_ms - config.trailing_pad_ms)
            trim_bytes = min(len(audio), self._ms_to_bytes(trim_ms))
            if trim_bytes > 0:
                audio = audio[: len(audio) - trim_bytes]
        kept_ms = self._bytes_to_ms(len(audio))
        start_ms = self._start_ms
        end_ms = start_ms + kept_ms
        # §4.4: the pre-roll is not speech, so it does not count toward `min_turn_ms`.
        speech_ms = end_ms - start_ms - config.pre_roll_ms
        discarded_short = speech_ms < config.min_turn_ms
        turn = DetectedTurn(
            turn_id=turn_id,
            turn_index=self._turn_index,
            audio=audio,
            start_ms=start_ms,
            end_ms=end_ms,
            is_barge_in=self._was_during_playback,
            pre_roll_ms=config.pre_roll_ms,
            end_reason=end_reason,
            discarded_short=discarded_short,
        )
        self._state = TurnDetectorState.IDLE
        self._speech_run_ms = 0
        self._silence_run_ms = 0
        self._was_during_playback = False
        self._turn_id = None
        self._accumulator = []
        self._accumulated_bytes = 0
        return turn
