"""`WavFileSink` — an incrementally written 16 kHz mono s16le WAV file (§9.1, D9).

A call recording cannot be assembled at the end: the process may die, and a session survives a
backend restart (SPEC §39). So the file is opened when the call starts and every frame is appended
as it arrives. The RIFF header is written once up front with placeholder sizes and patched with
the real ones on `close()`, which is what `wave.Wave_write` does internally — using the stdlib
module directly here means the header layout is the stdlib's problem, and `bytes_written` still
counts *payload* bytes only, so `audio_segments.byte_offset` stays a plain multiple of the frame
size and never has to account for the 44-byte header.

An interrupted process leaves a file whose header claims zero frames. That is a readable-enough
artefact (every tool recovers it from the file length) and, more importantly, the `audio_segments`
rows that point into it are already committed with true offsets, so the transcript and the score
remain reproducible (SPEC §28).
"""

from __future__ import annotations

import wave
from pathlib import Path

from app.application.voice.config import BYTES_PER_SAMPLE

__all__ = ["InMemoryAudioSink", "WavFileSink"]

#: The RIFF/WAVE header `wave` writes before the first sample. Subtracted nowhere — it exists as
#: documentation of why `bytes_written` is not the file size.
WAV_HEADER_BYTES = 44


class WavFileSink:
    """An `AudioSink` backed by a WAV file under `data_dir`."""

    def __init__(
        self,
        *,
        data_dir: Path,
        relative_path: str,
        sample_rate: int,
        num_channels: int = 1,
    ) -> None:
        self._relative_path = relative_path
        self._path = data_dir / relative_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = wave.open(str(self._path), "wb")  # noqa: SIM115 - closed by close()
        self._writer.setnchannels(num_channels)
        self._writer.setsampwidth(BYTES_PER_SAMPLE)
        self._writer.setframerate(sample_rate)
        self._bytes_written = 0
        self._closed = False

    @property
    def relative_path(self) -> str:
        """The path stored in `audio_segments.file_path`, relative to `Settings.data_dir`."""
        return self._relative_path

    @property
    def path(self) -> Path:
        """The absolute path on this machine (never persisted — SPEC §41)."""
        return self._path

    @property
    def bytes_written(self) -> int:
        """PCM bytes written so far, excluding the RIFF header."""
        return self._bytes_written

    def write(self, pcm: bytes) -> None:
        """Append PCM s16le bytes."""
        if self._closed:
            raise RuntimeError(f"{self._relative_path} is closed")
        self._writer.writeframes(pcm)
        self._bytes_written += len(pcm)

    def close(self) -> None:
        """Patch the header with the real sizes. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._writer.close()


class InMemoryAudioSink:
    """An `AudioSink` that keeps the PCM in a `bytearray` — for tests that need no file."""

    def __init__(self, relative_path: str) -> None:
        self._relative_path = relative_path
        #: Everything written, in write order.
        self.buffer = bytearray()
        self.closed = False

    @property
    def relative_path(self) -> str:
        """The path an `audio_segments` row would carry."""
        return self._relative_path

    @property
    def bytes_written(self) -> int:
        """PCM bytes written so far."""
        return len(self.buffer)

    def write(self, pcm: bytes) -> None:
        """Append PCM s16le bytes."""
        if self.closed:
            raise RuntimeError(f"{self._relative_path} is closed")
        self.buffer.extend(pcm)

    def close(self) -> None:
        """Mark the sink finished. Idempotent."""
        self.closed = True
