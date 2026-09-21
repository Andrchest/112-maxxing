"""The one score-reading Protocol the explanation slice may depend on (R8, SPEC §2, §29, D11).

`ScoreReportReader` is deliberately narrower than `app.application.ports.score_repository.
ScoreRepository`: it has `load_report` and nothing else — no `replace_for_session`. That is half
of R8's structural guarantee ("the explanation use case and its repository port have NO write
path to score tables"): `GenerateExplanation`/`GetExplanation` are constructed with this Protocol,
never with the real `ScoreRepository`, so there is no attribute on anything they hold that could
write a `score_results`/`score_evidence` row even if a future edit tried to call one.

The concrete adapter lives in the composition root (`app.api.container`, D2's "the ONE module
that wires ports to adapters") — not here — because building it means naming `ScoreRepository`,
which this package's modules must never do (the other half of the guarantee; see
`backend/tests/invariants/test_explanation_cannot_write_scores.py`, part (a)).

`ExplanationAudience` is not redefined here: `app.application.ports.
report_explanation_repository.ExplanationAudience` (E16-A) is the one type `GenerateExplanation`
reuses, so the request's audience, the prompt's tone and the stored row's audience are the same
Python type end to end.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.common.ids import SessionId
from app.domain.scoring.results import ScoreResult

__all__ = ["ScoreReportReader"]


@runtime_checkable
class ScoreReportReader(Protocol):
    """The one `ScoreRepository` method the explanation slice may call."""

    async def load_report(self, session_id: SessionId) -> tuple[ScoreResult, ...] | None:
        """This session's stored `score_results` (with evidence), or `None` if never scored."""
        ...
