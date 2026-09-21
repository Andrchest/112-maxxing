"""Real-model contract tests (E12 ruling 1).

Every test in this package is marked `requires_models` and is skipped unless
`SIM_RUN_MODEL_TESTS=1`, the relevant heavy package(s) import, and the relevant model path(s)
exist — see `_skip.require_model_env`. Run via `make test-models`; never part of `make gate`.
"""
