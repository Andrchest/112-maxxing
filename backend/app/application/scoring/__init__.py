"""Scoring persistence and session-end wiring (SPEC §28, D11, epic E15-B).

`app.domain.scoring` (E15-A) owns the pure `score()`, `ScoreReport`, `report_checksum` and
`scoring_events`. This package is everything around them: loading `(ScenarioVersion, ordered
SessionEvents)` without touching a materialized table (D5, R1), persisting `score_results` /
`score_evidence`, appending `SCORING_RULE_EVALUATED` in the same unit of work as the write it
belongs to (R2), and the re-score equality check `rescoreSession` exposes (`openapi.yaml`).
"""

from __future__ import annotations
