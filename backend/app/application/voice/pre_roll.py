"""`PreRollBuffer` — the audio that survives from before the VAD triggered (§4.2, SPEC §17).

A VAD needs sustained energy before it calls a frame speech, so by the time the `TurnDetector`
opens a turn the first syllable is already gone. The fix SPEC §17 names is a pre-roll buffer: a
fixed-capacity ring of the most recent resampled frames, copied to the front of the turn's
accumulator at the IDLE/PRE_SPEECH → IN_SPEECH transition, so the recognised audio begins
`pre_roll_ms` before the trigger.

Capacity is `ceil(pre_roll_ms / vad_frame_ms)` frames (default 300/32 → 10 frames = 320 ms ≥
300 ms): the ceiling, never the floor, because keeping slightly more than the configured pre-roll
costs a few kilobytes and keeping slightly less loses the consonant the buffer exists for.

The buffer is *not* cleared when a turn opens — its contents are already in the accumulator — and
is cleared by `reset()` at the start of a call.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from app.application.ports.call_transport import AudioFrame

__all__ = ["PreRollBuffer"]


class PreRollBuffer:
    """A fixed-capacity ring of the most recent frames (§4.2)."""

    def __init__(self, capacity_frames: int) -> None:
        if capacity_frames < 0:
            raise ValueError("a pre-roll buffer cannot hold a negative number of frames")
        self._frames: deque[AudioFrame] = deque(maxlen=capacity_frames or None)
        self._capacity = capacity_frames

    @property
    def capacity(self) -> int:
        """How many frames the buffer holds before it starts evicting."""
        return self._capacity

    def push(self, frame: AudioFrame) -> None:
        """Append a frame, evicting the oldest when the buffer is full."""
        if self._capacity == 0:
            return
        self._frames.append(frame)

    def frames(self) -> Iterator[AudioFrame]:
        """The buffered frames, oldest first."""
        return iter(tuple(self._frames))

    def pcm(self) -> bytes:
        """Every buffered frame's PCM, concatenated oldest-first."""
        return b"".join(frame.pcm for frame in self._frames)

    def duration_ms(self) -> int:
        """Total duration of the buffered audio."""
        return sum(frame.duration_ms for frame in self._frames)

    def clear(self) -> None:
        """Drop every buffered frame (called by `TurnDetector.reset()`)."""
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)
