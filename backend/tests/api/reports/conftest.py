"""Fixtures for the report API tests (E16-A) — the full 112 -> DDS cycle, plus a real WAV on disk.

The whole chain up to "the DDS incident is resolved" already exists and is re-exported by name,
exactly as `tests/api/dds/conftest.py` re-exports the handoff chain: `pytest_plugins` cannot
register a module that is already loaded as a real conftest, so the fixtures are bound as module
attributes instead.

Two additions of this package's own:

* `api_settings` is overridden to put `data_dir` under the test's `tmp_path`, so
  `getAudioSegment` reads from a directory this test owns and a path-escape assertion has
  something real to escape *from*;
* `recorded_segment` writes an actual WAV file and the `audio_segments` row that points into it.
  The fake call transport records no audio, so the Range tests would otherwise have nothing to
  serve — and a Range test against a stubbed byte string would prove nothing about the seek.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.application.ports.inference_metric_repository import StoredInferenceMetric
from app.application.ports.transcript_segment_repository import StoredTranscriptSegment
from app.config.settings import Settings
from app.domain.common.ids import SessionId

from tests.api import conftest as _api_fixtures
from tests.api.dds import conftest as _dds_fixtures
from tests.api.handoff import conftest as _handoff_fixtures
from tests.api.operator import conftest as _operator_fixtures

pytestmark = pytest.mark.integration

OperatorFlow = _handoff_fixtures.OperatorFlow

# -- the API base (real Postgres, real Redis, the production container) ------------------------
client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
tokens = _api_fixtures.tokens
users = _api_fixtures.users
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
demo_version_id = _api_fixtures.demo_version_id
unit_of_work = _api_fixtures.unit_of_work
auth = _api_fixtures.auth

# -- the 112 half -----------------------------------------------------------------------------
flow = _operator_fixtures.flow
ringing = _operator_fixtures.ringing
connected = _operator_fixtures.connected
interview = _operator_fixtures.interview
uow_factory = _operator_fixtures.uow_factory

# -- handoff, transition and the DDS stage ------------------------------------------------------
clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
prepared = _handoff_fixtures.prepared
handed_off = _handoff_fixtures.handed_off
in_transition = _handoff_fixtures.in_transition
dds_active = _handoff_fixtures.dds_active

# -- DDS levers ---------------------------------------------------------------------------------
dds_post = _dds_fixtures.dds_post
dds_get = _dds_fixtures.dds_get
acknowledge = _dds_fixtures.acknowledge
open_selection = _dds_fixtures.open_selection
select = _dds_fixtures.select
dispatch = _dds_fixtures.dispatch
at = _dds_fixtures.at
events_of = _dds_fixtures.events_of
event_types = _dds_fixtures.event_types


@pytest.fixture
def api_settings(_api_settings_base: Settings, tmp_path: Path) -> Settings:
    """The API settings with `data_dir` inside the test's own directory (see the docstring)."""
    data_dir = tmp_path / "data"
    (data_dir / "recordings").mkdir(parents=True)
    return _api_settings_base.model_copy(update={"data_dir": str(data_dir)})


#: The unmodified fixture, bound under a private name so the override above can build on it.
_api_settings_base = _api_fixtures.api_settings


@pytest.fixture
async def resolved(dds_active: OperatorFlow, clock: Any) -> OperatorFlow:
    """The shortest road to a `RESOLVED` DDS incident — the same one `test_full_cycle.py` drives.

    Copied rather than imported so this package does not depend on another test module's private
    fixture ordering; the timing is the demo scenario's, documented there.
    """
    await acknowledge(dds_active)
    await open_selection(dds_active)
    await at(dds_active, clock, 300_000)
    assert (await select(dds_active, "АЦ-1")).status_code == 200
    await dispatch(dds_active)
    await at(dds_active, clock, 560_000)
    return dds_active


@pytest.fixture
async def completed(
    resolved: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> OperatorFlow:
    """`closeDdsIncident` — the last stage, so the session completes and is scored — plus the
    voice artefacts the pipeline writes in production.

    The chain runs on `FakeCallTransport` with no ASR, TTS or recorder attached (that is what
    makes four hundred simulated seconds cost milliseconds), so `transcript_segments`,
    `audio_segments`, `dialogue_turns` and `inference_metrics` would all be empty and SPEC §29
    items 5, 6, 7 and 13 would have nothing to render. The rows seeded here are exactly the rows
    E12/E14 write for a real call — same tables, same columns, same `audio_segment_id` link — so
    the report is exercised against a realistic session rather than a hollow one. Nothing seeded
    here is read by `score()` (D5, D11): the score comes from the event log the chain really
    produced.
    """
    response = await dds_post(resolved, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code == 200, response.text
    await _seed_voice_artefacts(resolved, api_settings, uow_factory)
    return resolved


async def _seed_voice_artefacts(
    flow: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> None:
    """One recorded operator turn and one caller turn, as E12/E14 would have written them."""
    session_id = SessionId(flow.session_id)
    operator_audio = await _write_wav(flow, api_settings, "trainee")
    caller_audio = await _write_wav(flow, api_settings, "caller")
    now = datetime.now(UTC)

    async with uow_factory() as uow:
        stage_id = (await uow.sessions.get(session_id)).stages[0].role_stage_id
        await uow.audio_segments.add_all(
            [
                StoredAudioSegment(
                    id=operator_audio.audio_segment_id,
                    session_id=session_id,
                    speaker="TRAINEE",
                    file_path=operator_audio.relative_path,
                    start_ms=1000,
                    end_ms=1200,
                    sample_rate=16000,
                    num_channels=1,
                    byte_offset=0,
                    byte_length=len(operator_audio.pcm),
                    created_at=now,
                ),
                StoredAudioSegment(
                    id=caller_audio.audio_segment_id,
                    session_id=session_id,
                    speaker="CALLER",
                    file_path=caller_audio.relative_path,
                    start_ms=2000,
                    end_ms=2200,
                    sample_rate=16000,
                    num_channels=1,
                    byte_offset=0,
                    byte_length=len(caller_audio.pcm),
                    created_at=now,
                ),
            ]
        )
        await uow.transcript_segments.add(
            StoredTranscriptSegment(
                id=uuid4(),
                session_id=session_id,
                audio_segment_id=operator_audio.audio_segment_id,
                speaker="TRAINEE",
                start_ms=1000,
                end_ms=1200,
                text="Служба 112, что у вас случилось?",
                confidence=0.94,
                asr_provider="fake",
                asr_model="fake-asr",
                turn_index=0,
            )
        )
        await uow.transcript_segments.add(
            StoredTranscriptSegment(
                id=uuid4(),
                session_id=session_id,
                audio_segment_id=caller_audio.audio_segment_id,
                speaker="CALLER",
                start_ms=2000,
                end_ms=2200,
                text="У нас пожар в квартире!",
                turn_index=0,
            )
        )
        await uow.dialogue_turns.upsert(
            DialogueTurnUpsert(
                id=uuid4(),
                session_id=session_id,
                role_stage_id=stage_id,
                turn_index=0,
                user_speech_started_offset_ms=1000,
                user_speech_ended_offset_ms=1200,
            )
        )
        await uow.dialogue_turns.set_speech_end_to_first_audio_ms(session_id, 0, 880)
        for component, ttft, total in (
            ("ASR", None, 210),
            ("LLM_INTERPRETER", 95, 300),
            ("LLM_GENERATOR", 140, 520),
            ("TTS", 60, 400),
        ):
            await uow.inference_metrics.add(
                StoredInferenceMetric(
                    id=uuid4(),
                    session_id=session_id,
                    request_id=f"{flow.session_id}-{component}",
                    component=component,
                    provider="fake",
                    model="fake",
                    turn_index=0,
                    started_at=now,
                    ttft_ms=ttft,
                    total_latency_ms=total,
                )
            )
        await uow.commit()


@dataclass(frozen=True)
class _WrittenWav:
    audio_segment_id: UUID
    relative_path: str
    pcm: bytes


async def _write_wav(flow: OperatorFlow, api_settings: Settings, who: str) -> _WrittenWav:
    """A real 200 ms 16 kHz mono s16le WAV under `DATA_DIR/recordings/{session_id}/`."""
    pcm = bytes(range(256)) * 25
    relative = f"recordings/{flow.session_id}/{who}-{uuid4()}.wav"
    path = Path(api_settings.data_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)
    return _WrittenWav(audio_segment_id=uuid4(), relative_path=relative, pcm=pcm)


@dataclass(frozen=True)
class RecordedSegment:
    """The operator's seeded `audio_segments` row and the WAV it points into."""

    audio_segment_id: UUID
    path: Path
    byte_length: int
    representation_bytes: int
    """`44 + byte_length` — the length of the representation `getAudioSegment` serves."""


@pytest.fixture
async def recorded_segment(
    completed: OperatorFlow, api_settings: Settings, uow_factory: Any
) -> RecordedSegment:
    """The operator-side segment `completed` seeded, read back through the repository."""
    async with uow_factory() as uow:
        segments = await uow.audio_segments.list_for_session(SessionId(completed.session_id))
        await uow.commit()
    segment = next(item for item in segments if str(item.speaker) == "TRAINEE")
    assert segment.file_path is not None
    return RecordedSegment(
        audio_segment_id=segment.id,
        path=Path(api_settings.data_dir) / segment.file_path,
        byte_length=segment.byte_length,
        representation_bytes=44 + segment.byte_length,
    )


async def report(flow: OperatorFlow, *, token: str | None = None) -> httpx.Response:
    """`getSessionReport` as the instructor unless another token is given."""
    return await flow.client.get(
        f"/api/v1/reports/{flow.session_id}",
        headers=auth(token or flow.instructor_token),
    )


async def release(flow: OperatorFlow, *, token: str | None = None) -> httpx.Response:
    """`releaseReportToTrainee`."""
    return await flow.client.post(
        f"/api/v1/instructor/sessions/{flow.session_id}/report/release",
        headers=auth(token or flow.instructor_token),
    )
