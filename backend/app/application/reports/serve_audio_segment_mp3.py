"""`getAudioSegmentMp3` — MP3 download of one audio segment (I5 E40, Q-E16-3 variant b).

ТЗ ¶369 allows «MP3 or WAV» for a call recording download and the WAV one already exists
(`getAudioSegment`, `serve_audio_segment.py`); ¶383 requires MP3 specifically. The owner's answer
of 2026-09-26 to Q-E16-3 is variant (б) — add the MP3 download rather than replace WAV with it —
so this is a second representation of the same `audio_segments` row, not a new resource.

**What is encoded.** `ServeAudioSegment.resolve_audio` (this task's addition to that module) does
the authorization, lookup and file read exactly as the WAV download does, and hands back the
segment's raw PCM (no container header, no `Range` slicing — the whole segment, since ТЗ ¶383 asks
for a downloadable file, not a seekable stream). That PCM is what `Mp3Encoder.encode` transcodes;
the format (mono, the segment's own sample rate, 64 kbit/s CBR) is the I5 E40 brief's decision, not
a choice made here.

**Cache key.** `<sha256>.mp3`, written next to the segment's WAV file
(`DATA_DIR/recordings/{session_id}/…`). The hash is taken over the WAV *representation*
`getAudioSegment` would answer a plain `200` with (the 44-byte header plus the PCM) rather than
the bare PCM, so `<sha>.mp3` names the same content identity the WAV download's bytes would — two
segments (or the same segment re-encoded after a hypothetical format change upstream) never
collide on one cache file, and the same segment always reuses its own.

**Authorization.** Identical to `getAudioSegment` (E16 R3/R7): `resolve_audio` raises the same
`SessionNotFoundError` / `ForbiddenForRoleError` / `AudioSegmentNotFoundError` / `AudioPurgedError`
the WAV endpoint raises, from the same code, so a trainee without access gets the same refusal for
either format.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.mp3_encoder import Mp3Encoder
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.serve_audio_segment import ServeAudioSegment, wav_header
from app.domain.common.ids import SessionId

__all__ = ["AudioSegmentMp3Response", "ServeAudioSegmentMp3"]


@dataclass(frozen=True, slots=True)
class AudioSegmentMp3Response:
    """What the router turns into a `Response`: the MP3 bytes and their media type."""

    content: bytes
    media_type: str = "audio/mpeg"


class ServeAudioSegmentMp3:
    """`getAudioSegmentMp3`: the same segment's audio, transcoded to MP3, cached by content hash.

    Composes a `ServeAudioSegment` for its authorization/lookup/file-read rather than duplicating
    it, so the two operations' access rule can never drift apart (E16 R3/R7).
    """

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, recordings_dir: Path, encoder: Mp3Encoder
    ) -> None:
        self._wav = ServeAudioSegment(unit_of_work, recordings_dir=recordings_dir)
        self._encoder = encoder

    async def __call__(
        self, session_id: SessionId, audio_segment_id: UUID, user: AuthenticatedUser
    ) -> AudioSegmentMp3Response:
        segment, pcm, wav_path = await self._wav.resolve_audio(session_id, audio_segment_id, user)
        header = wav_header(
            sample_rate=segment.sample_rate, num_channels=segment.num_channels, data_bytes=len(pcm)
        )
        digest = hashlib.sha256(header + pcm).hexdigest()
        cache_path = wav_path.parent / f"{digest}.mp3"
        if cache_path.is_file():
            return AudioSegmentMp3Response(content=cache_path.read_bytes())

        mp3 = self._encoder.encode(
            pcm, sample_rate=segment.sample_rate, num_channels=segment.num_channels
        )
        cache_path.write_bytes(mp3)
        return AudioSegmentMp3Response(content=mp3)
