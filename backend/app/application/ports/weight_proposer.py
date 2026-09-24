"""`WeightProposer` port — difficulty-weight proposals for a lesson's cards (HLD 70 §70.3.7,
I3 E9a).

One call per lesson: the proposer receives every card's `CardMetadata` (scenario metadata only —
never a `ScenarioVersion`, never world truth) and answers one `ProposedWeight` per card. It never
writes anything: the use case stores the answer as proposals, and only the instructor's accept
turns a proposal into `PlanEntry.weight` (SPEC §2, D11).

Two adapters (`app.infrastructure.weights`): `HeuristicWeightProposer`, deterministic, what the
gate runs; and `LlmWeightProposer`, one JSON-schema-constrained `LLMClient` call, which answers
the heuristic's proposals on any failure of the model or of its output.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.lesson.weights import CardMetadata, ProposalSource, ProposedWeight

__all__ = ["WeightProposals", "WeightProposer"]


class WeightProposals(BaseModel):
    """A proposer's answer for one lesson: one `ProposedWeight` per card, in plan order."""

    model_config = ConfigDict(frozen=True)

    source: ProposalSource
    model_name: str | None = None
    fallback_reason: str | None = None
    """Set when an LLM adapter fell back to the heuristic (e.g. `LLM_UNAVAILABLE`)."""
    items: tuple[ProposedWeight, ...]


@runtime_checkable
class WeightProposer(Protocol):
    """Propose a weight (integer 1–10) and a short Russian reason for every card."""

    async def propose(self, cards: Sequence[CardMetadata], *, request_id: str) -> WeightProposals:
        """Never raises for a model failure — an adapter that can fail answers its fallback."""
        ...
