"""The ten scoring evaluators (HLD `10-domain-model.md` §10.14) plus their registry.

Each `<evaluator>.py` module holds that evaluator's Pydantic config model and its
`evaluate(rule, config, ctx) -> ScoreResult`. `registry.py` maps every `EvaluatorType` to both —
the config model that validates a `ScoringRule.config` at scenario import time (§30.8 item 20) and
the `evaluate` that scores it — under one totality assert each, so an `EvaluatorType` cannot be
half-wired.
"""
