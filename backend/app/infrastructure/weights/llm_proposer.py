"""`LlmWeightProposer` — weight proposals from the local LLM, the heuristic on any failure
(HLD 70 §70.3.7, I3 E9a; SPEC §2, D10, D11).

One `LLMClient.complete` per lesson, constrained by `weight_prompt.RESPONSE_FORMAT`; the prompt
is `weight_prompt.build_messages(cards)` — `CardMetadata` only. Every way the call can fail
answers `HeuristicWeightProposer`'s proposals with a `fallback_reason`:

* `LLM_TIMEOUT` — `LlmTimeoutError` or `asyncio.TimeoutError`;
* `LLM_UNAVAILABLE` — `LlmUnavailableError` or any other exception from the client;
* `LLM_INVALID_OUTPUT` — an answer that is cut off, is not JSON, or does not name every position
  once with an integer weight in 1..10 and a reason (`parse_proposals`).

Nothing here writes: the use case stores the answer as proposals and only the instructor's accept
turns one into a weight.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.application.lessons.weight_prompt import (
    RESPONSE_FORMAT,
    WeightProposalOutputError,
    build_messages,
    parse_proposals,
)
from app.application.ports.llm import LLMClient, LlmTimeoutError
from app.application.ports.weight_proposer import WeightProposals
from app.domain.lesson.weights import CardMetadata, ProposalSource
from app.infrastructure.weights.heuristic_proposer import HeuristicWeightProposer

__all__ = ["LlmWeightProposer"]

logger = logging.getLogger(__name__)


class LlmWeightProposer:
    """`WeightProposer` over an `LLMClient`, with `HeuristicWeightProposer` as its fallback."""

    def __init__(
        self,
        llm: LLMClient,
        fallback: HeuristicWeightProposer,
        *,
        max_tokens: int,
        temperature: float,
        timeout_ms: int,
    ) -> None:
        self._llm = llm
        self._fallback = fallback
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout_ms = timeout_ms

    async def propose(self, cards: Sequence[CardMetadata], *, request_id: str) -> WeightProposals:
        if not cards:
            return self._fallback.propose_now(cards)
        positions = [card.position for card in cards]
        try:
            completion = await self._llm.complete(
                build_messages(cards),
                request_id=request_id,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format=RESPONSE_FORMAT,
                timeout_ms=self._timeout_ms,
            )
        except (LlmTimeoutError, TimeoutError):
            logger.warning("weight proposals %s: the LLM timed out; heuristic used", request_id)
            return self._fallback.propose_now(cards, fallback_reason="LLM_TIMEOUT")
        except Exception:
            logger.warning(
                "weight proposals %s: the LLM failed; heuristic used", request_id, exc_info=True
            )
            return self._fallback.propose_now(cards, fallback_reason="LLM_UNAVAILABLE")
        try:
            if completion.finish_reason != "stop":
                raise WeightProposalOutputError(f"finish_reason={completion.finish_reason}")
            items = parse_proposals(completion.text, positions)
        except WeightProposalOutputError as exc:
            logger.warning("weight proposals %s: invalid LLM output (%s)", request_id, exc)
            return self._fallback.propose_now(cards, fallback_reason="LLM_INVALID_OUTPUT")
        return WeightProposals(source=ProposalSource.LLM, model_name=completion.model, items=items)
