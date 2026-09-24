"""The API's routers (D8).

Eleven modules, one per group of `openapi.yaml` operations: `auth` and `users` (D8's accounts),
`health`, `scenarios`, `sessions`, `operator` (the Operator 112 commands), `dds` (the DDS stage
commands and reads), `snapshot` (`getSessionSnapshot`), `realtime` (`listSessionEvents` and the
WebSocket), `reports` (the whole `reports` tag — `getSessionReport`, `rescoreSession`,
`getAudioSegment`, `listInferenceMetrics` and the explanation pair) and `instructor`
(`releaseReportToTrainee`, `getInstructorSessionOverview`), plus I3's `reference` (the reference
pack reads, HLD 70 §70.6), `lessons` (HLD 70 §70.3; two routers — `releaseLessonReport` is pathed
under `/api/v1/instructor`), `incidents` (`listMyIncidents`) and `groups` (I3 E9a's trainee
groups, HLD 70 §70.3.7), and I3 E6e's `telephony` (the SIP gateway's four operations, HLD 80
§80.2.3; gated by the gateway's service credential). Every one of them is included by
`create_app`, and the contract test walks the registered routes, so an operation added to an
existing module needs no change to `create_app` and is checked against the contract
automatically.

`reports` exports two routers — `router` under `/api/v1/reports` and `audio_router` under
`/api/v1/sessions`, because `getAudioSegment` is tagged `reports` but pathed under its session.

Every module here may import `app.application` and `app.api` only. Never `app.infrastructure`,
never `app.db`, and never a domain *layer* type from `app.domain.layers` — a response is an
`app.api.schemas` model built by an explicit mapping function (D2, D3).
`backend/tests/api/test_router_layering.py` scans this package and fails on any of them.
"""

from __future__ import annotations

from app.api.routers import (
    auth,
    dds,
    groups,
    health,
    incidents,
    instructor,
    lessons,
    operator,
    realtime,
    reference,
    reports,
    scenarios,
    sessions,
    snapshot,
    telephony,
    users,
)

__all__ = [
    "auth",
    "dds",
    "groups",
    "health",
    "incidents",
    "instructor",
    "lessons",
    "operator",
    "realtime",
    "reference",
    "reports",
    "scenarios",
    "sessions",
    "snapshot",
    "telephony",
    "users",
]
