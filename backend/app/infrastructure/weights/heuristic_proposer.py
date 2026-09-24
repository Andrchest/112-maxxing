"""`HeuristicWeightProposer` — the deterministic `WeightProposer` (HLD 70 §70.3.7, I3 E9a)."""

from __future__ import annotations

from collections.abc import Sequence

from app.application.ports.weight_proposer import WeightProposals
from app.domain.lesson.weights import CardMetadata, ProposalSource, heuristic_weights

__all__ = ["HeuristicWeightProposer"]


class HeuristicWeightProposer:
    """`2 × difficulty` plus one per complicating factor, in 1..10 (`heuristic_weight`)."""

    async def propose(self, cards: Sequence[CardMetadata], *, request_id: str) -> WeightProposals:
        return self.propose_now(cards)

    def propose_now(
        self, cards: Sequence[CardMetadata], *, fallback_reason: str | None = None
    ) -> WeightProposals:
        """The same answer, synchronously — what `LlmWeightProposer` falls back to."""
        return WeightProposals(
            source=ProposalSource.HEURISTIC,
            fallback_reason=fallback_reason,
            items=heuristic_weights(cards),
        )
