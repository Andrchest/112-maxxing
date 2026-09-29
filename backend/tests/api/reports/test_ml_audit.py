"""Smoke: real migrations + PostgreSQL + HTTP + auth + persistence + worker leases."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.application.reports.ml_audit_service import MLAuditWorker
from app.db.models.ml_audit import MLAuditJob
from app.db.models.session import SimulationSession
from app.infrastructure.persistence.ml_audit_repository import SqlAlchemyMLAuditRepository

from tests.api.conftest import auth
from tests.api.reports.conftest import release, report

pytestmark = pytest.mark.integration


async def test_ml_audit_http_persists_round_trip_and_leaves_scores_unchanged(completed, container):
    path = f"/api/v1/reports/{completed.session_id}/ml-audit"
    headers = auth(completed.instructor_token)
    before = (await report(completed)).json()["score_report"]
    assert (await completed.client.get(path, headers=headers)).json() is None
    response = await completed.client.post(path, headers=headers)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["run_id"] and first["generated_at"]
    assert first["score_percent"] is None  # Fake provider never masquerades as real ML.
    assert first["rubric_version"] == "fire-training-v1"
    assert (await completed.client.get(path, headers=headers)).json() == first
    second = await completed.client.post(path + "?regenerate=true", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["run_id"] != first["run_id"]
    assert (await report(completed)).json()["score_report"] == before
    async with container.session_factory() as db:
        assert await db.scalar(sa.text("SELECT count(*) FROM ml_audit_runs")) == 2


async def test_audit_preserves_release_and_role_visibility(completed, tokens):
    path = f"/api/v1/reports/{completed.session_id}/ml-audit"
    assert (await completed.client.get(path)).status_code == 401
    response = await completed.client.post(path, headers=auth(completed.instructor_token))
    assert response.status_code == 200
    # A trainee cannot read an instructor's cached audit before report release.
    denied = await completed.client.get(path, headers=auth(tokens["trainee1"]))
    assert denied.status_code == 403, denied.text
    await release(completed)
    operator = await completed.client.get(path, headers=auth(tokens["trainee1"]))
    assert operator.status_code == 200, operator.text
    # DDS-only viewer has a different visible-input hash; no 112 quotes can leak.
    dds = await completed.client.get(path, headers=auth(tokens["trainee2"]))
    assert dds.status_code == 200, dds.text
    assert dds.json() is None


async def test_durable_worker_claim_retry_and_stale_token(completed, container):
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.update(SimulationSession)
            .where(
                SimulationSession.id == completed.session_id,
            )
            .values(completed_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    repo = SqlAlchemyMLAuditRepository(container.session_factory)
    claimed = await repo.claim()
    assert claimed is not None
    session_id, token = claimed
    assert session_id == completed.session_id
    assert await repo.claim() is None  # Lease prevents another worker claiming it.
    await repo.finish(session_id, uuid4(), success=True)  # Stale/non-owner cannot finish.
    async with container.session_factory() as db:
        assert not await db.scalar(sa.select(MLAuditJob.done))
    await repo.finish(session_id, token, success=False)
    for _attempt in range(2, 4):
        async with container.session_factory.begin() as db:
            await db.execute(
                sa.update(MLAuditJob).values(
                    available_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        claimed = await repo.claim()
        assert claimed is not None
        await repo.finish(*claimed, success=False)
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.update(MLAuditJob).values(
                available_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    assert await repo.claim() is None  # Exhausted three attempts, no busy retry loop.


async def test_automatic_worker_creates_saved_result_without_http_post(completed, container):
    async with container.session_factory.begin() as db:
        await db.execute(
            sa.update(SimulationSession)
            .where(
                SimulationSession.id == completed.session_id,
            )
            .values(completed_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    worker = MLAuditWorker(container.ml_audit_service())
    assert await worker.tick()
    response = await completed.client.get(
        f"/api/v1/reports/{completed.session_id}/ml-audit",
        headers=auth(completed.instructor_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["run_id"]
