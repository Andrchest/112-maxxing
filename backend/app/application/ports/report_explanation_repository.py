"""`ReportExplanationRepository` port — `report_explanations` (HLD §20.10, D11, SPEC §29, §2).

The optional LLM explanation of an already-computed `ScoreReport`, stored *separately* from the
numbers it talks about. The port is deliberately narrow: load one, store one. It exposes no way to
reach `score_results` / `score_evidence`, which is half of the epic's structural guarantee that
"the explanation cannot write score tables" — the other half being that the use case is
constructed with a read-only score reader (`backend/tests/invariants/`).

`score_report_checksum` is carried, never recomputed here: it is the value
`app.domain.scoring.engine.report_checksum` produced for the report the prose was generated from,
echoed so a client can verify that the numbers did not move (SPEC §2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from app.domain.common.ids import SessionId

__all__ = [
    "EXPLANATION_AUDIENCES",
    "ExplanationAudience",
    "ReportExplanationRepository",
    "StoredReportExplanation",
]

#: `openapi.yaml`'s `ReportExplanation.audience` / `GenerateExplanationRequest.audience`.
ExplanationAudience = Literal["TRAINEE", "INSTRUCTOR"]

#: The same two members as a runtime tuple, for validation and table-driven tests.
EXPLANATION_AUDIENCES: tuple[ExplanationAudience, ...] = ("TRAINEE", "INSTRUCTOR")


@dataclass(frozen=True, slots=True)
class StoredReportExplanation:
    """One `report_explanations` row — `openapi.yaml`'s `ReportExplanation` plus the row id."""

    id: UUID
    session_id: SessionId
    audience: ExplanationAudience
    text_ru: str
    generated_at: datetime
    llm_provider: str
    llm_model: str
    score_report_checksum: str


@runtime_checkable
class ReportExplanationRepository(Protocol):
    """Read and upsert one session's stored explanations."""

    async def get(
        self, session_id: SessionId, audience: ExplanationAudience
    ) -> StoredReportExplanation | None:
        """The stored explanation for `(session_id, audience)`, or `None` when none exists.

        `None` is exactly `getReportExplanation`'s `404` and, on the POST path, the difference
        between generating and `409 EXPLANATION_ALREADY_EXISTS`.
        """
        ...

    async def list_for_session(self, session_id: SessionId) -> list[StoredReportExplanation]:
        """Every stored explanation of `session_id`, ordered by `audience`.

        `getSessionReport` needs only whether the list is non-empty (`explanation_available`); it
        never renders the prose, which is a resource of its own (D11).
        """
        ...

    async def upsert(self, explanation: StoredReportExplanation) -> UUID:
        """Insert, or replace the row `UNIQUE (session_id, audience)` already holds.

        Replacement is what `regenerate: true` means; without it the caller must refuse with
        `EXPLANATION_ALREADY_EXISTS` *before* calling this — the repository does not police a
        product rule.
        """
        ...
