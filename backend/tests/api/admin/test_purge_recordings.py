"""`purgeRecordings` over HTTP (`POST /api/v1/admin/recordings/purge`, ADMIN only, R8).

`backend/tests/integration/recording/test_purge_recordings.py` already proves the use case itself
in depth (real files, a full completed+scored session, idempotency, the missing-file case, the
rescore checksum). This module is the HTTP surface only: the role gate, the default `dry_run: true`
body, and that the response is the documented `PurgeRecordingsResult`.

`api_settings` is overridden (same reasoning as `tests.api.reports.conftest`) so `data_dir` lives
under this test's own `tmp_path` — a real WAV is written and deleted here, and it must never touch
the repository's own `data/` directory.
"""

from __future__ import annotations

import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from app.application.ports.audio_segment_repository import StoredAudioSegment
from app.config.settings import Settings
from app.db.models.session import SimulationSession as SimulationSessionRow
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.api import conftest as _api_fixtures
from tests.api.conftest import auth, create_demo_session, participant

#: The unmodified fixture, bound under a private name so the override below can build on it
#: (`tests.api.reports.conftest` uses the same pattern for the same reason).
_api_settings_base = _api_fixtures.api_settings

pytestmark = pytest.mark.integration


@pytest.fixture
def api_settings(_api_settings_base: Settings, tmp_path: Path) -> Settings:
    """`_api_settings_base` with `data_dir` under this test's own `tmp_path` (see the docstring)."""
    data_dir = tmp_path / "data"
    (data_dir / "recordings").mkdir(parents=True)
    return _api_settings_base.model_copy(update={"data_dir": str(data_dir)})


def _participants(users: dict[str, UserId]) -> list[dict[str, Any]]:
    return [
        participant(users["trainee1"], "OPERATOR_112"),
        participant(users["trainee2"], "DDS"),
    ]


async def _seed_recording(
    unit_of_work: Any, api_settings: Settings, session_id: UUID, *, days_old: int
) -> Path:
    """A real WAV under `api_settings.data_dir`, its `audio_segments` row, and a session old
    enough to be past any reasonable retention window (via `created_at` — this session never
    completes, so §9.2's "or `created_at` for a session that never completed" is the reference)."""
    pcm = bytes(range(256)) * 25
    relative = f"recordings/{session_id}/trainee-{uuid4()}.wav"
    path = Path(api_settings.data_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm)

    async with unit_of_work() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        await uow.audio_segments.add_all(
            [
                StoredAudioSegment(
                    id=uuid4(),
                    session_id=SessionId(session_id),
                    speaker="TRAINEE",
                    file_path=relative,
                    start_ms=0,
                    end_ms=200,
                    sample_rate=16000,
                    num_channels=1,
                    byte_offset=0,
                    byte_length=len(pcm),
                    created_at=datetime.now(UTC),
                )
            ]
        )
        await uow.session.execute(
            sa.update(SimulationSessionRow.__table__)
            .where(SimulationSessionRow.__table__.c.id == session_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days_old))
        )
        await uow.commit()
    return path


async def _created_session(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    demo_version_id: ScenarioVersionId,
    users: dict[str, UserId],
) -> UUID:
    created = await create_demo_session(
        client, tokens["instructor1"], demo_version_id, _participants(users)
    )
    return UUID(created["id"])


async def test_admin_dry_run_lists_without_deleting(
    client: httpx.AsyncClient,
    api_settings: Settings,
    unit_of_work: Any,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    session_id = await _created_session(client, tokens, demo_version_id, users)
    path = await _seed_recording(unit_of_work, api_settings, session_id, days_old=40)

    response = await client.post(
        "/api/v1/admin/recordings/purge",
        headers=auth(tokens["admin1"]),
        json={"dry_run": True, "session_id": str(session_id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["segment_count"] == 1
    assert body["bytes_freed"] > 0
    assert body["reason"] == "MANUAL_REQUEST"
    assert path.is_file(), "dry-run must not delete anything"


async def test_admin_real_purge_deletes_the_file_with_no_body_default(
    client: httpx.AsyncClient,
    api_settings: Settings,
    unit_of_work: Any,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> None:
    """A bare `POST` with a body of just `{"dry_run": false}` still runs the routine sweep."""
    session_id = await _created_session(client, tokens, demo_version_id, users)
    path = await _seed_recording(unit_of_work, api_settings, session_id, days_old=40)

    response = await client.post(
        "/api/v1/admin/recordings/purge", headers=auth(tokens["admin1"]), json={"dry_run": False}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is False
    assert body["segment_count"] == 1
    assert body["reason"] == "RETENTION_WINDOW"
    assert not path.is_file(), "a real purge must delete the file"


@pytest.mark.parametrize("username", ["instructor1", "trainee1"])
async def test_a_non_admin_is_refused_and_nothing_is_purged(
    client: httpx.AsyncClient,
    api_settings: Settings,
    unit_of_work: Any,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
    username: str,
) -> None:
    session_id = await _created_session(client, tokens, demo_version_id, users)
    path = await _seed_recording(unit_of_work, api_settings, session_id, days_old=40)

    response = await client.post(
        "/api/v1/admin/recordings/purge",
        headers=auth(tokens[username]),
        json={"dry_run": False},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"
    assert path.is_file()


async def test_without_a_token_it_is_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/admin/recordings/purge", json={"dry_run": True})

    assert response.status_code == 401, response.text
