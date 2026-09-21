"""`ScoringEvidenceError` (HLD `10-domain-model.md` §10.14, D11, SPEC §42 test 11).

Its own module so that both `engine.py` and the ten evaluator modules can raise it without
`engine` and `evaluators` importing each other. `engine` re-exports the name, which is where
§10.14 says it lives.
"""

from __future__ import annotations

from app.domain.common.errors import ScoringEvidenceError

__all__ = ["ScoringEvidenceError"]


# One class, defined where §10.1 puts the domain hierarchy (`app.domain.common.errors`, a
# `DomainError`), re-exported here: a hard error, never a silent zero and never a fabricated
# reference. Raised when an evaluator returns fewer than `max(1, rule.min_evidence)` pieces of
# evidence, and when an "absence" has no bounding event to point at — which cannot happen on a
# well-formed log, because scoring runs only after `SESSION_COMPLETED` has been appended (R2).
