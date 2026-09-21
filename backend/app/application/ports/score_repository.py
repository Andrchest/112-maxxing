"""`ScoreRepository` port — `score_results` / `score_evidence` (HLD `20-db-schema.md` §20.7, D11).

Derived, recomputable storage: every row here comes from a `ScoreReport` a `score()` call already
produced (D5, SPEC §28). The port therefore never *builds* a `ScoreResult` — it only stores and
reloads the ones the pure domain gave it, exactly as given (R2, R3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import ScenarioVersionId, SessionId
from app.domain.scoring.results import ScoreReport, ScoreResult

__all__ = ["ScoreRepository"]


@runtime_checkable
class ScoreRepository(Protocol):
    """Read and replace one session's scoring output."""

    async def replace_for_session(
        self,
        session_id: SessionId,
        scenario_version_id: ScenarioVersionId,
        report: ScoreReport,
    ) -> None:
        """Delete this session's `score_results` (cascades to `score_evidence`) and re-insert
        `report.results`, one `score_evidence` row per `ScoreResult.evidence` entry.

        Runs inside the caller's Unit of Work; the unique `(session_id, rule_id)` constraint is
        what makes a re-score replace rather than duplicate (`20-db-schema.md` §20.7). An empty
        `report.results` (a scenario with no rules — not the demo scenario, but not forbidden
        either) deletes any stale rows and inserts nothing.
        """
        ...

    async def load_report(self, session_id: SessionId) -> tuple[ScoreResult, ...] | None:
        """This session's stored `score_results`, each with its real `score_evidence`, in the
        scenario's rule `order_index` — or `None` when nothing has been scored yet.

        `None` and `()` are distinct: a scenario with zero scoring rules would (in principle)
        produce `()`; a session that has never been scored has no rows to read at all and answers
        `None`, which `rescoreSession` renders as `stored_checksum: null`.
        """
        ...
