"""`getAudioSegment` over real HTTP: a real WAV on disk, real byte ranges (E16 R7, D9, §9.1).

The served representation is `44 + byte_length` bytes — a canonical RIFF header for *this
segment*, then its PCM copied verbatim — so every assertion below is about bytes that actually
came off the disk. A Range test against a stubbed body would prove nothing about the seek that
SPEC §29 item 7 asks for.
"""

from __future__ import annotations

import struct
from typing import Any

import pytest

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, RecordedSegment, release

pytestmark = pytest.mark.integration

HEADER_BYTES = 44


def _url(flow: OperatorFlow, segment: RecordedSegment) -> str:
    return f"/api/v1/sessions/{flow.session_id}/audio/{segment.audio_segment_id}"


async def _get(
    flow: OperatorFlow,
    segment: RecordedSegment,
    *,
    range_header: str | None = None,
    token: str | None = None,
) -> Any:
    headers = auth(token or flow.instructor_token)
    if range_header is not None:
        headers = {**headers, "Range": range_header}
    return await flow.client.get(_url(flow, segment), headers=headers)


# -- 200: the whole segment --------------------------------------------------------------------


async def test_without_a_range_the_whole_segment_is_served(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    response = await _get(completed, recorded_segment)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-range" not in response.headers
    assert len(response.content) == recorded_segment.representation_bytes


async def test_the_body_is_a_playable_wav_describing_this_segment(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    """The header is built for the *slice*: reusing the call file's header would report the whole
    call's duration for a two-hundred-millisecond segment."""
    body = (await _get(completed, recorded_segment)).content

    assert body[:4] == b"RIFF"
    assert body[8:12] == b"WAVE"
    assert struct.unpack("<I", body[40:44])[0] == recorded_segment.byte_length
    assert struct.unpack("<I", body[24:28])[0] == 16000
    assert struct.unpack("<H", body[22:24])[0] == 1


# -- 206: partial content ----------------------------------------------------------------------


async def test_a_range_answers_206_with_content_range(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    total = recorded_segment.representation_bytes
    response = await _get(completed, recorded_segment, range_header="bytes=0-99")

    assert response.status_code == 206, response.text
    assert response.headers["content-range"] == f"bytes 0-99/{total}"
    assert response.headers["accept-ranges"] == "bytes"
    assert len(response.content) == 100


async def test_ranges_reassemble_into_the_whole_representation(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    """The property that makes seeking correct: the parts are the whole, byte for byte."""
    whole = (await _get(completed, recorded_segment)).content
    total = recorded_segment.representation_bytes
    midpoint = total // 2

    first = await _get(completed, recorded_segment, range_header=f"bytes=0-{midpoint - 1}")
    second = await _get(completed, recorded_segment, range_header=f"bytes={midpoint}-")

    assert first.status_code == second.status_code == 206
    assert first.content + second.content == whole


async def test_a_suffix_range_returns_the_tail(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    whole = (await _get(completed, recorded_segment)).content
    response = await _get(completed, recorded_segment, range_header="bytes=-64")

    assert response.status_code == 206
    assert response.content == whole[-64:]


async def test_a_range_past_the_header_reads_real_pcm(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    whole = (await _get(completed, recorded_segment)).content
    response = await _get(
        completed, recorded_segment, range_header=f"bytes={HEADER_BYTES}-{HEADER_BYTES + 15}"
    )

    assert response.status_code == 206
    assert response.content == whole[HEADER_BYTES : HEADER_BYTES + 16]


# -- 416 ----------------------------------------------------------------------------------------


async def test_an_unsatisfiable_range_answers_416(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    beyond = recorded_segment.representation_bytes + 1000
    response = await _get(completed, recorded_segment, range_header=f"bytes={beyond}-")

    assert response.status_code == 416, response.text
    assert response.json()["code"] == "RANGE_NOT_SATISFIABLE"
    assert response.headers["content-range"] == f"bytes */{recorded_segment.representation_bytes}"


# -- 410 / 404 ----------------------------------------------------------------------------------


async def test_a_purged_segment_answers_410(
    completed: OperatorFlow, recorded_segment: RecordedSegment, uow_factory: Any
) -> None:
    """D9's retention purge nulls `file_path` and keeps the row as an audit record."""
    import sqlalchemy as sa

    async with uow_factory() as uow:
        await uow.session.execute(
            sa.text("UPDATE audio_segments SET file_path = NULL, purged_at = now() WHERE id = :i"),
            {"i": recorded_segment.audio_segment_id},
        )
        await uow.commit()

    response = await _get(completed, recorded_segment)
    assert response.status_code == 410, response.text
    assert response.json()["code"] == "AUDIO_PURGED"


async def test_a_stored_path_that_escapes_the_recordings_directory_is_refused(
    completed: OperatorFlow, recorded_segment: RecordedSegment, uow_factory: Any
) -> None:
    """SPEC §41: nothing in the request touches the path, and a tampered row is not read either."""
    import sqlalchemy as sa

    async with uow_factory() as uow:
        await uow.session.execute(
            sa.text("UPDATE audio_segments SET file_path = :p WHERE id = :i"),
            {"p": "../../etc/passwd", "i": recorded_segment.audio_segment_id},
        )
        await uow.commit()

    response = await _get(completed, recorded_segment)
    assert response.status_code == 404, response.text


async def test_an_unknown_segment_is_a_404(completed: OperatorFlow) -> None:
    response = await completed.client.get(
        f"/api/v1/sessions/{completed.session_id}/audio/00000000-0000-4000-8000-0000000000ff",
        headers=auth(completed.instructor_token),
    )
    assert response.status_code == 404, response.text


# -- access: the transcript's rule (R3/R7) -------------------------------------------------------


async def test_the_dds_trainee_may_not_listen_to_the_call(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    """A viewer who may not read the transcript may not hear it either."""
    assert (await release(completed)).status_code == 200
    response = await _get(completed, recorded_segment, token=completed.dds_token)
    assert response.status_code == 403, response.text


async def test_the_operator_trainee_may_listen_once_released(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    assert (await release(completed)).status_code == 200
    response = await _get(completed, recorded_segment, token=completed.operator_token)
    assert response.status_code == 200, response.text


async def test_the_operator_trainee_is_refused_before_release(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    response = await _get(completed, recorded_segment, token=completed.operator_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "REPORT_NOT_RELEASED"
