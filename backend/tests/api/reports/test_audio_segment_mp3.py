"""`getAudioSegmentMp3` over real HTTP (I5 E40, Q-E16-3 variant b): a real WAV on disk, a real
LAME encode, and the same access rule `getAudioSegment` (`test_audio_segment.py`) already proves.

Three things this suite pins that a pure unit test cannot: the endpoint really answers
`audio/mpeg`, a second request for the same segment never re-encodes (asserted by making a second
encode raise), and a trainee refused the WAV gets the identical refusal for MP3.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.infrastructure.recording.mp3_encoder import LameMp3Encoder

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, RecordedSegment, release

pytestmark = pytest.mark.integration


def _url(flow: OperatorFlow, segment: RecordedSegment) -> str:
    return f"/api/v1/sessions/{flow.session_id}/audio/{segment.audio_segment_id}/mp3"


async def _get(flow: OperatorFlow, segment: RecordedSegment, *, token: str | None = None) -> Any:
    return await flow.client.get(_url(flow, segment), headers=auth(token or flow.instructor_token))


def _is_mp3_frame_sync(body: bytes) -> bool:
    """The 11-bit frame sync every MPEG audio frame starts with (`0xFF` then top 3 bits set)."""
    return len(body) >= 2 and body[0] == 0xFF and (body[1] & 0xE0) == 0xE0


# -- 200: a real MP3 -----------------------------------------------------------------------------


async def test_the_body_is_audio_mpeg_with_a_valid_frame_header(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    response = await _get(completed, recorded_segment)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert _is_mp3_frame_sync(response.content)


async def test_the_cache_is_hit_on_a_second_request(
    completed: OperatorFlow, recorded_segment: RecordedSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`<sha>.mp3` is written next to the WAV on the first request; the second must read it back
    rather than encode again — proven by making a second `encode()` call fail the test outright."""
    first = await _get(completed, recorded_segment)
    assert first.status_code == 200, first.text

    cache_files = list(recorded_segment.path.parent.glob("*.mp3"))
    assert len(cache_files) == 1, cache_files

    def _boom(self: LameMp3Encoder, *args: Any, **kwargs: Any) -> bytes:
        raise AssertionError("encode() must not run again once the cache file exists")

    monkeypatch.setattr(LameMp3Encoder, "encode", _boom)

    second = await _get(completed, recorded_segment)
    assert second.status_code == 200, second.text
    assert second.content == first.content


# -- 410 / 404 — identical to the WAV endpoint's --------------------------------------------------


async def test_a_purged_segment_answers_410(
    completed: OperatorFlow, recorded_segment: RecordedSegment, uow_factory: Any
) -> None:
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


async def test_an_unknown_segment_is_a_404(completed: OperatorFlow) -> None:
    response = await completed.client.get(
        f"/api/v1/sessions/{completed.session_id}/audio/00000000-0000-4000-8000-0000000000ff/mp3",
        headers=auth(completed.instructor_token),
    )
    assert response.status_code == 404, response.text


# -- access: the same rule as getAudioSegment (R3/R7) --------------------------------------------


async def test_the_dds_trainee_may_not_listen_to_the_call(
    completed: OperatorFlow, recorded_segment: RecordedSegment
) -> None:
    """A viewer refused the WAV (`test_audio_segment.py`) is refused MP3 too, the same way."""
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
