"""`admin` schemas — `PurgeRecordingsRequest`, `PurgeRecordingsResult` (`openapi.yaml`, §9.2, R8).

`clearInferenceFatal` needs no schema of its own beyond `HealthReadyResponseSchema` (already
`app.api.schemas.health`); this module is `purgeRecordings`'s half only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.application.recording import PurgeRecordingsRequest, PurgeRecordingsResult
from app.domain.common.ids import SessionId

__all__ = [
    "PurgeRecordingsRequestSchema",
    "PurgeRecordingsResultSchema",
    "purge_recordings_request",
    "purge_recordings_result_schema",
]


class PurgeRecordingsRequestSchema(ApiModel):
    """`openapi.yaml`'s `PurgeRecordingsRequest`. The whole body is optional on the wire — a bare
    `POST` with no body is the default `dry_run=True` sweep (`Settings.recording_retention_days`,
    no `session_id`) — so the router hands this a schema instance built from `{}` when the request
    carries no body at all, never `None`.
    """

    dry_run: bool = True
    older_than_days: int | None = Field(default=None, ge=0)
    session_id: UUID | None = None


class PurgeRecordingsResultSchema(ApiModel):
    """`openapi.yaml`'s `PurgeRecordingsResult`."""

    dry_run: bool
    retention_days: int = Field(ge=0)
    session_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    bytes_freed: int = Field(ge=0)
    purged_at: datetime
    reason: Literal["RETENTION_WINDOW", "MANUAL_REQUEST", "ADMIN_DELETE"]


def purge_recordings_request(schema: PurgeRecordingsRequestSchema) -> PurgeRecordingsRequest:
    """`PurgeRecordingsRequestSchema` -> the application `PurgeRecordingsRequest`."""
    return PurgeRecordingsRequest(
        dry_run=schema.dry_run,
        older_than_days=schema.older_than_days,
        session_id=SessionId(schema.session_id) if schema.session_id is not None else None,
    )


def purge_recordings_result_schema(result: PurgeRecordingsResult) -> PurgeRecordingsResultSchema:
    """The application `PurgeRecordingsResult` -> `PurgeRecordingsResultSchema`."""
    return PurgeRecordingsResultSchema(
        dry_run=result.dry_run,
        retention_days=result.retention_days,
        session_count=result.session_count,
        segment_count=result.segment_count,
        bytes_freed=result.bytes_freed,
        purged_at=result.purged_at,
        reason=result.reason,  # type: ignore[arg-type]  # the use case only ever writes these three
    )
