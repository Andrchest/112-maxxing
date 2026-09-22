"""`HeadlessTraineeClient` — a trainee-side LiveKit client with no browser (E19, HLD 60 §7.4).

`benchmarks/benchmark_e2e.py --transport livekit` needs something that behaves like the trainee's
browser: join the room with a backend-minted token, publish 16 kHz mono PCM read from a WAV as the
trainee's microphone track, subscribe to the caller's track and note when its first frame arrives.

It lives **here**, beside `LiveKitCallTransport`, for the same reason that file gives: this
package is the only place the LiveKit SDK may be imported (D9, SPEC §15), and
`backend/tools/check_imports.py` forbids `livekit` under `backend/**`, `workers/voice_agent/tests`
and `benchmarks/**`. The benchmark imports this class; it never imports `livekit` itself.

Like `LiveKitCallTransport`, the SDK is imported **inside** the methods, not at module scope, so
the class stays importable — and its shape testable — on a machine that has never installed the
optional extra.

**The first-audio wall time this client records is a cross-check, never the reported number.**
SPEC §27's `speech_end_to_first_audio_ms` is read from the session event log (HLD §7.4: "taken
from the session event log itself so the benchmark and the product metric cannot diverge"); a
subscriber's own clock includes the far end's jitter buffer and is only useful for catching a
transport-level surprise.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["HeadlessTraineeClient", "PublishedTurn"]

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16_000
_CHANNELS = 1
_FRAME_MS = 20
_TRACK_NAME = "trainee-microphone"


@dataclass
class PublishedTurn:
    """One WAV turn published into the room, and what came back."""

    turn_id: str
    path: Path
    published_at_ms: float
    first_caller_audio_at_ms: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def first_audio_wall_ms(self) -> float | None:
        """Cross-check only — the reported metric is the event log's (module docstring)."""
        if self.first_caller_audio_at_ms is None:
            return None
        return self.first_caller_audio_at_ms - self.published_at_ms


class HeadlessTraineeClient:
    """Joins a room as the trainee, publishes WAV turns, listens for the caller's first audio."""

    def __init__(self, *, url: str, token: str, room: str) -> None:
        self._url = url
        self._token = token
        self._room_name = room
        self._room: Any = None
        self._source: Any = None
        self._first_caller_audio_at_ms: float | None = None
        #: Set by the subscriber the moment the caller's first frame of the *current* turn lands.
        self._caller_audio_seen = asyncio.Event()
        self._audio_tasks: list[asyncio.Task[None]] = []
        #: Every turn published, in order.
        self.turns: list[PublishedTurn] = []

    @property
    def room_name(self) -> str:
        return self._room_name

    async def connect(self) -> None:
        """`rtc.Room().connect(url, token)` and publish the trainee's microphone track."""
        from livekit import rtc

        room = rtc.Room()

        @room.on("track_subscribed")
        def _on_track(track: Any, *_rest: Any) -> None:
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._audio_tasks.append(asyncio.create_task(self._watch_caller(track)))

        await room.connect(self._url, self._token)
        source = rtc.AudioSource(_SAMPLE_RATE, _CHANNELS)
        track = rtc.LocalAudioTrack.create_audio_track(_TRACK_NAME, source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._room = room
        self._source = source

    async def _watch_caller(self, track: Any) -> None:
        """Record when the caller's first audio frame of each turn arrived (cross-check only).

        The loop deliberately does **not** stop at the first frame: a call has many turns and the
        track is subscribed once, so a subscriber that returned after turn 1 would leave every
        later turn with no cross-check at all — and would stop draining the stream. Each
        `publish_wav` re-arms the two pieces of per-turn state below; every other frame is consumed
        and dropped, because this client is a measuring instrument, not a player.
        """
        from livekit import rtc

        stream = rtc.AudioStream.from_track(track=track, sample_rate=_SAMPLE_RATE, num_channels=1)
        try:
            async for _event in stream:
                if self._first_caller_audio_at_ms is None:
                    self._first_caller_audio_at_ms = time.perf_counter() * 1000.0
                    self._caller_audio_seen.set()
        finally:
            await stream.aclose()

    async def publish_wav(
        self, path: Path, *, turn_id: str, realtime: bool = True
    ) -> PublishedTurn:
        """Publish one 16 kHz mono WAV as the trainee's speech, in `_FRAME_MS` frames.

        `realtime=True` paces the frames at their own duration, which is what makes the VAD see a
        turn rather than one instantaneous burst — and what makes the room's timeline and the wall
        clock the same timeline, so `speech_end_to_first_audio_ms` in the event log is a real-time
        latency rather than a scripted one.

        Per-turn cross-check state is re-armed here, before the first frame goes out.
        """
        from livekit import rtc

        if self._source is None:
            raise RuntimeError("connect() first")
        with wave.open(str(path), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise ValueError(f"{path}: expected 16-bit mono PCM")
            if handle.getframerate() != _SAMPLE_RATE:
                raise ValueError(f"{path}: expected {_SAMPLE_RATE} Hz")
            pcm = handle.readframes(handle.getnframes())

        self._first_caller_audio_at_ms = None
        self._caller_audio_seen.clear()
        samples = (_SAMPLE_RATE * _FRAME_MS) // 1000
        step = samples * 2
        turn = PublishedTurn(turn_id=turn_id, path=path, published_at_ms=time.perf_counter() * 1000)
        for start in range(0, len(pcm) - step + 1, step):
            await self._source.capture_frame(
                rtc.AudioFrame(
                    data=pcm[start : start + step],
                    sample_rate=_SAMPLE_RATE,
                    num_channels=_CHANNELS,
                    samples_per_channel=samples,
                )
            )
            if realtime:
                await asyncio.sleep(_FRAME_MS / 1000.0)
        self.turns.append(turn)
        return turn

    async def wait_for_caller_audio(self, *, timeout_s: float = 20.0) -> float | None:
        """Wait for the caller's first frame; returns the wall-clock ms since publish, or `None`.

        `None` means the caller never spoke within `timeout_s` — the benchmark records that as a
        missing cross-check and still reports whatever the event log holds, because the log is the
        authority (module docstring).
        """
        try:
            await asyncio.wait_for(self._caller_audio_seen.wait(), timeout=timeout_s)
        except TimeoutError:
            return None
        turn = self.turns[-1] if self.turns else None
        if turn is None or self._first_caller_audio_at_ms is None:
            return None
        turn.first_caller_audio_at_ms = self._first_caller_audio_at_ms
        return turn.first_audio_wall_ms

    async def close(self) -> None:
        """Stop the subscriber tasks, close the source, leave the room. Idempotent."""
        for task in self._audio_tasks:
            task.cancel()
            with contextlib.suppress(BaseException):  # best-effort teardown
                await task
        self._audio_tasks.clear()
        if self._source is not None:
            try:
                await self._source.aclose()
            except Exception:
                logger.exception("closing the headless client's audio source failed")
            self._source = None
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception:
                logger.exception("disconnecting the headless client failed")
            self._room = None
