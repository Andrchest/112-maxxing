"""`listInferenceMetrics` — SPEC §27 telemetry for one session, plus the §29 item 13 aggregate.

`InferenceMetricsPage` is `{items, total, timing_metrics}`. Three decisions worth stating:

* `total` is the count **before** `limit`, after `component`: a client that asked for 500 of 1200
  ASR rows must be able to tell that there are 1200. Filtering after counting would make the two
  numbers describe different sets;
* `timing_metrics` is the *whole session's* aggregate, computed by the same
  `reports.timing_metrics` function the report uses and over the **unfiltered** rows. A p50 that
  moved when the reader ticked a component filter would be a different metric with the same name,
  and SPEC §27 names one;
* the newest rows come first (`started_at` descending), so a truncated page shows the end of the
  session — which is where a latency problem is usually looked for — and ties break on
  `request_id`, which is unique (§20.6), so the page is deterministic.

Filtering in the use case rather than in the port is deliberate: `InferenceMetricRepository`
exposes `list_for_session` and nothing else, one session's rows are a few thousand at most, and
the aggregate needs the unfiltered list anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.inference_metric_repository import StoredInferenceMetric
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.reports.timing_metrics import TimingMetrics, timing_metrics
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId

__all__ = ["InferenceMetricsPage", "ListInferenceMetrics"]

#: `openapi.yaml`'s `limit` bounds for this operation.
DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class InferenceMetricsPage:
    """`openapi.yaml`'s `InferenceMetricsPage`."""

    items: tuple[StoredInferenceMetric, ...]
    total: int
    timing_metrics: TimingMetrics


class ListInferenceMetrics:
    """`listInferenceMetrics` — readable by anyone who may observe the session (D8).

    Telemetry is not incident data: it names models, latencies and token counts, never what the
    caller said or what the world truth is, so it carries no `DataVisibilityPolicy` decision. The
    gate is the ordinary "may this caller see that this session exists" one.
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        component: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> InferenceMetricsPage:
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            if session is None:
                raise SessionNotFoundError(session_id)
            if not can_observe(session, user):
                raise ForbiddenForRoleError(f"the caller may not observe session {session_id}")
            rows = await uow.inference_metrics.list_for_session(session_id)
            turns = await uow.dialogue_turns.list_for_session(session_id)
            events = tuple(await uow.events.read(session_id))
            await uow.commit()

        matching = [row for row in rows if component is None or str(row.component) == component]
        matching.sort(key=lambda row: (row.started_at, row.request_id), reverse=True)
        bounded = max(1, min(limit, MAX_LIMIT))
        return InferenceMetricsPage(
            items=tuple(matching[:bounded]),
            total=len(matching),
            # The whole session's aggregate, from the unfiltered rows: one metric, one name.
            timing_metrics=timing_metrics(turns, rows, events),
        )
