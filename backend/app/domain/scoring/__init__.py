"""Scoring domain (HLD `10-domain-model.md` §10.14, D11, SPEC §28).

`rules.py` holds `ScoringRule`; `results.py` the four result shapes; `context.py` the read model
built once from `(ScenarioVersion, ordered SessionEvents)`; `comparisons.py` the five comparison
modes; `evidence.py` the evidence constructors and the single `ScoreResult` factory;
`errors.py` `ScoringEvidenceError`; `evaluators/` the ten `evaluate(...)` functions and their
registry; and `engine.py` `score()`, `report_checksum()` and `scoring_events()`.

Everything in this package is pure: no I/O, no LLM, no clock, no `uuid4`, no materialized tables
(SPEC §2, §42 tests 9-11). `backend/tests/invariants/test_inv_09_*` scans the package to keep it
that way.
"""
