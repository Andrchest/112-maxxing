"""`getAudioSegment` — SPEC §29 item 6 (audio playback) with real HTTP Range (E16 R7, D9, §9.1).

**What the resource is.** One `audio_segments` row, served as a self-contained WAV: a 44-byte
RIFF header describing that row's `sample_rate` / `num_channels` / `byte_length`, followed by the
row's PCM bytes copied verbatim out of the session's recording file. The bytes are a slice, so the
row's `byte_offset` / `byte_length` locate them without a scan — exactly what `openapi.yaml` says
the two columns are for — and there is **no transcoding**: the samples that reach the client are
the samples the sink wrote.

The 44-byte header is prepended rather than the file's own header re-used because a segment is a
*slice*: the file's header describes the whole call, and a player handed the middle of a file
would report the wrong duration. `WAV_HEADER_BYTES` is the same constant `WavFileSink` documents.

**Range.** The representation served is `44 + byte_length` bytes long, and `Range` is interpreted
against that, not against the file:

* no `Range` header → `200` with the whole representation and `Accept-Ranges: bytes`;
* `Range: bytes=a-b`, `bytes=a-`, `bytes=-n` → `206` with `Content-Range: bytes a-b/total`;
* a range that starts past the end, or a syntactically broken one that still names a range →
  `416 RANGE_NOT_SATISFIABLE` with `Content-Range: bytes */total` (RFC 9110 §14.4).

**Path safety (SPEC §41).** The only input to the path is the row's stored *relative* path. It is
joined onto the configured recordings directory, fully resolved, and rejected unless the result is
still inside that directory — so a row whose `file_path` was tampered with to `../../etc/passwd`
answers `404`, not a file. Nothing in the request influences the path at all.

**Purged (D9).** `purged_at` set, or `file_path` nulled, is `410 AUDIO_PURGED`: the retention
purge deletes the audio and keeps the row as an audit record, and the report is expected to render
the transcript without playback rather than to pretend the recording never existed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.visibility import report_visibility
from app.application.sessions.authorisation import resolve_participant
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId

__all__ = [
    "WAV_HEADER_BYTES",
    "AudioPurgedError",
    "AudioSegmentNotFoundError",
    "AudioSegmentResponse",
    "RangeNotSatisfiableError",
    "ServeAudioSegment",
    "parse_range",
    "wav_header",
]

#: PCM integer WAV: `WAVE_FORMAT_PCM`.
_PCM_FORMAT = 1
_BITS_PER_SAMPLE = 16

#: The canonical RIFF/WAVE header length. Restated here rather than imported from
#: `app.infrastructure.recording.wav_writer` (which documents the same constant for the same
#: reason): the application layer may not import infrastructure (D2), and 44 is a property of the
#: file format, not of the sink that happens to write it.
WAV_HEADER_BYTES = 44


class AudioPurgedError(DomainError):
    """The retention purge deleted the recording (`410 AUDIO_PURGED`, D9)."""

    code = "AUDIO_PURGED"

    def __init__(self, audio_segment_id: UUID) -> None:
        self.audio_segment_id = audio_segment_id
        super().__init__(f"audio segment {audio_segment_id} was purged by the retention policy")


class AudioSegmentNotFoundError(DomainError):
    """No such row, or its file is not where the row says (`404 NOT_FOUND`)."""

    code = "NOT_FOUND"

    def __init__(self, audio_segment_id: UUID) -> None:
        self.audio_segment_id = audio_segment_id
        super().__init__(f"no audio segment {audio_segment_id}")


class RangeNotSatisfiableError(DomainError):
    """The requested range lies outside the representation (`416`, RFC 9110 §14.4)."""

    code = "RANGE_NOT_SATISFIABLE"

    def __init__(self, total: int) -> None:
        self.total = total
        #: The `Content-Range` a `416` must carry: the size, and no satisfied range.
        self.content_range = f"bytes */{total}"
        super().__init__(f"the requested range is not satisfiable for {total} bytes")


@dataclass(frozen=True, slots=True)
class AudioSegmentResponse:
    """What the router turns into a `Response`: the bytes and the three headers that matter."""

    status_code: int
    content: bytes
    total_bytes: int
    content_range: str | None
    media_type: str = "audio/wav"


def wav_header(*, sample_rate: int, num_channels: int, data_bytes: int) -> bytes:
    """A 44-byte canonical RIFF/WAVE header for `data_bytes` of s16le PCM."""
    byte_rate = sample_rate * num_channels * (_BITS_PER_SAMPLE // 8)
    block_align = num_channels * (_BITS_PER_SAMPLE // 8)
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_bytes,
        b"WAVE",
        b"fmt ",
        16,
        _PCM_FORMAT,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        _BITS_PER_SAMPLE,
        b"data",
        data_bytes,
    )


def parse_range(header: str | None, total: int) -> tuple[int, int] | None:
    """`(first, last)` inclusive for a single byte range, `None` when there is no `Range` header.

    Raises `RangeNotSatisfiableError` for a range that names nothing readable. A `Range` this
    function does not understand at all (a unit other than `bytes`, or a multi-range request) is
    treated as absent, which RFC 9110 §14.2 explicitly permits — the client then gets the whole
    representation rather than an error.
    """
    if header is None:
        return None
    value = header.strip()
    if not value.lower().startswith("bytes=") or "," in value:
        return None
    spec = value[len("bytes=") :].strip()
    first_text, separator, last_text = spec.partition("-")
    if not separator:
        return None

    if not first_text:
        # `bytes=-N`: the final N bytes.
        if not last_text.isdigit():
            return None
        suffix = int(last_text)
        if suffix == 0 or total == 0:
            raise RangeNotSatisfiableError(total)
        return max(0, total - suffix), total - 1

    if not first_text.isdigit():
        return None
    first = int(first_text)
    last = int(last_text) if last_text.isdigit() else total - 1
    if first >= total or last < first:
        raise RangeNotSatisfiableError(total)
    return first, min(last, total - 1)


class ServeAudioSegment:
    """`getAudioSegment`: the same access rule as the transcript (R3, R7).

    A viewer who may not see the transcript may not hear it either, so this use case builds the
    *same* `ReportVisibility` the report does and refuses on `shows_operator_sections`. That is
    why it is here rather than beside the recording infrastructure: the rule is a report rule.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, *, recordings_dir: Path) -> None:
        self._unit_of_work = unit_of_work
        #: `DATA_DIR/recordings` (D9). Every served path must resolve inside it.
        self._recordings_dir = recordings_dir

    async def __call__(
        self,
        session_id: SessionId,
        audio_segment_id: UUID,
        user: AuthenticatedUser,
        *,
        range_header: str | None = None,
    ) -> AudioSegmentResponse:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not user.is_instructor_or_admin:
                resolve_participant(session, user)
            released = await uow.sessions.get_report_release(session_id) is not None
            visibility = report_visibility(session, user, released=released)
            if not visibility.shows_operator_sections:
                raise ForbiddenForRoleError(
                    f"the caller may not listen to the audio of session {session_id}"
                )
            segment = await uow.audio_segments.get(audio_segment_id)
            await uow.commit()

        if segment is None or str(segment.session_id) != str(session_id):
            # A segment of *another* session is a 404, not a 403: the caller learns nothing about
            # a session they may not see (the same reasoning `getSession` applies).
            raise AudioSegmentNotFoundError(audio_segment_id)
        if segment.purged_at is not None or segment.file_path is None:
            raise AudioPurgedError(audio_segment_id)
        return self._serve(segment, range_header)

    # -- the bytes ----------------------------------------------------------------------------

    def _serve(self, segment: StoredAudioSegment, range_header: str | None) -> AudioSegmentResponse:
        path = self._resolved_path(segment)
        header = wav_header(
            sample_rate=segment.sample_rate,
            num_channels=segment.num_channels,
            data_bytes=segment.byte_length,
        )
        total = len(header) + segment.byte_length
        requested = parse_range(range_header, total)
        if requested is None:
            return AudioSegmentResponse(
                status_code=200,
                content=header + self._pcm(path, segment, 0, segment.byte_length),
                total_bytes=total,
                content_range=None,
            )

        first, last = requested
        chunk = bytearray()
        if first < len(header):
            chunk += header[first : min(last + 1, len(header))]
        pcm_first = max(0, first - len(header))
        pcm_last = last - len(header)
        if pcm_last >= 0:
            chunk += self._pcm(path, segment, pcm_first, pcm_last - pcm_first + 1)
        return AudioSegmentResponse(
            status_code=206,
            content=bytes(chunk),
            total_bytes=total,
            content_range=f"bytes {first}-{last}/{total}",
        )

    def _resolved_path(self, segment: StoredAudioSegment) -> Path:
        """`recordings_dir / <the row's relative path>`, refused if it escapes (SPEC §41).

        The row's `file_path` is relative to `DATA_DIR` and begins `recordings/…`
        (`app.application.voice.recorder`), so the join is against `DATA_DIR` and the containment
        check against `DATA_DIR/recordings`.
        """
        relative = str(segment.file_path or "")
        base = self._recordings_dir.resolve()
        candidate = (base.parent / relative).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            raise AudioSegmentNotFoundError(segment.id)
        return candidate

    @staticmethod
    def _pcm(path: Path, segment: StoredAudioSegment, offset: int, length: int) -> bytes:
        """`length` PCM bytes starting `offset` into the segment's own slice of the file."""
        if length <= 0:
            return b""
        with path.open("rb") as handle:
            handle.seek(WAV_HEADER_BYTES + segment.byte_offset + offset)
            return handle.read(min(length, max(0, segment.byte_length - offset)))
