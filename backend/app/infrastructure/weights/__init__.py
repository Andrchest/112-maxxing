"""`WeightProposer` adapters (HLD 70 §70.3.7, I3 E9a).

`HeuristicWeightProposer` — deterministic, `app.domain.lesson.weights.heuristic_weights`; the
gate's proposer and every fallback. `LlmWeightProposer` — one JSON-schema-constrained
`LLMClient` call per lesson over `app.application.lessons.weight_prompt`, answering the heuristic
on any failure of the model or of its output.
"""

from __future__ import annotations
