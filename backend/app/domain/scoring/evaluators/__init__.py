"""The ten scoring-evaluator config models (HLD `10-domain-model.md` §10.14) plus their registry.

Each `<evaluator>.py` module defines only that evaluator's config model — the `evaluate(...)`
function itself is E15's slice (see the `# TODO(E15): ...` line at the bottom of each module).
`registry.py` maps every `EvaluatorType` to its config model and validates a `ScoringRule.config`
against it.
"""
