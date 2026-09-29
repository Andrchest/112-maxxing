"""Authorisation precedes persisted result access and inference."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.application.reports.explanation.errors import ReportNotReadyError
from app.application.reports.ml_audit import AuditReport, Criterion, Rubric, input_checksum
from app.application.reports.ml_audit_service import MLAuditService, MLAuditWorker
from app.application.reports.visibility import ReportNotReleasedError
from app.application.sessions.authorisation import ParticipantNotAssignedError
from app.domain.common.ids import SessionId
from app.domain.enums import SessionState


@pytest.mark.parametrize("kind", ["unreleased", "unfinished", "stranger"])
async def test_report_gate_failure_never_invokes_model_or_cache(kind):
    session_id = SessionId(uuid4())
    errors = {
        "unreleased": ReportNotReleasedError(session_id),
        "unfinished": ReportNotReadyError(session_id, SessionState.ACTIVE),
        "stranger": ParticipantNotAssignedError(session_id),
    }
    reader = AsyncMock(side_effect=errors[kind])
    repository = SimpleNamespace(latest=AsyncMock())
    auditor = SimpleNamespace(evaluate=AsyncMock())
    service = MLAuditService(reader, repository, auditor, Mock(), engine_key="test", available=True)
    for call in [service.get, service.generate]:
        with pytest.raises(type(errors[kind])):
            await call(session_id, object())
    repository.latest.assert_not_called()
    auditor.evaluate.assert_not_called()


def setup_service():
    session_id = SessionId(uuid4())
    rubric = Rubric(
        version="v1",
        criteria=(
            Criterion(
                id="test",
                category="test",
                question="test?",
                weight=1,
                source="dialogue",
            ),
        ),
    )
    view = SimpleNamespace(
        session_id=session_id,
        session=SimpleNamespace(role_chain=("OPERATOR_112",)),
        transcript=[],
        timeline=[],
        final_card=None,
        score_report=SimpleNamespace(scenario_version_id=uuid4()),
    )
    result = AuditReport(
        model="test",
        rubric_version="v1",
        rubric_checksum="r",
        input_checksum="i",
        score_percent=100,
        coverage_percent=100,
        categories=(),
        results=(),
        sources=(),
    )
    repository = SimpleNamespace(
        latest=AsyncMock(return_value=None),
        save=AsyncMock(),
        claim=AsyncMock(return_value=(session_id, uuid4())),
        finish=AsyncMock(),
    )
    auditor = SimpleNamespace(evaluate=AsyncMock(return_value=result))
    service = MLAuditService(
        AsyncMock(return_value=view),
        repository,
        auditor,
        Mock(return_value=rubric),
        engine_key="test",
        available=True,
    )
    return service, session_id, result


async def test_generation_is_persisted_with_identity_and_timestamp():
    service, session_id, _ = setup_service()
    result = await service.generate(session_id, object())
    assert result.run_id is not None and result.generated_at is not None
    service.repository.save.assert_awaited_once_with(session_id, "test", result)
    assert service.repository.latest.call_args.args[1] == input_checksum((), ())


async def test_cache_and_explicit_regeneration():
    service, session_id, result = setup_service()
    service.repository.latest.return_value = result
    assert await service.generate(session_id, object()) is result
    service.auditor.evaluate.assert_not_called()
    new = await service.generate(session_id, object(), regenerate=True)
    assert new.run_id is not None
    service.auditor.evaluate.assert_awaited_once()


async def test_unknown_results_are_retried_not_cached_forever():
    service, session_id, result = setup_service()
    service.repository.latest.return_value = result.model_copy(update={"score_percent": None})
    await service.generate(session_id, object())
    service.auditor.evaluate.assert_awaited_once()


async def test_worker_finishes_successful_job():
    service, _, _ = setup_service()
    assert await MLAuditWorker(service).tick()
    assert service.repository.finish.call_args.kwargs == {"success": True}


async def test_worker_error_releases_lease_for_retry():
    service, _, _ = setup_service()
    service.reader.side_effect = RuntimeError("database unavailable")
    assert await MLAuditWorker(service).tick()
    assert service.repository.finish.call_args.kwargs == {"success": False}


async def test_worker_start_stop_leaves_no_task():
    import asyncio

    service, _, _ = setup_service()
    service.repository.claim.return_value = None
    worker = MLAuditWorker(service)
    before = asyncio.all_tasks()
    await worker.start()
    await asyncio.sleep(0)
    await worker.stop()
    assert asyncio.all_tasks() == before
