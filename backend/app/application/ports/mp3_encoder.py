"""`Mp3Encoder` port — the PCM-to-MP3 step of `getAudioSegmentMp3` (I5 E40, Q-E16-3 variant b).

Kept as a port so `app.application.reports.serve_audio_segment_mp3` never imports the real LAME
binding (D2: the application layer may not import infrastructure). The adapter,
`app.infrastructure.recording.mp3_encoder.LameMp3Encoder`, wraps the third-party `lameenc` package
(LGPL LAME, bundled as a compiled extension — no system `ffmpeg`/`lame` binary, which the container
does not have; see `docs/hld/71-i4-wave4.md` §71.18.1 for the licence note).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Mp3Encoder"]


@runtime_checkable
class Mp3Encoder(Protocol):
    def encode(self, pcm: bytes, *, sample_rate: int, num_channels: int) -> bytes:
        """s16le PCM → a complete MP3 stream (frames only, no ID3 tag)."""
        ...
