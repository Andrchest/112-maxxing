"""The optional LLM explanation of an already-computed `ScoreReport` (epic E16-B, SPEC §2, §29,
D11).

D11: "Optional LLM explanation is generated only from an already persisted `ScoreReport`, stored
separately, and cannot write to score tables." That guarantee is structural, not a comment: no
module in this package imports `ScoreRepository`, `uow.scores`' write method
(`replace_for_session`), `score_session` or `rescore_session` — `backend/tests/invariants/
test_explanation_cannot_write_scores.py` pins it with an AST scan mirroring `test_inv_03_*`, plus
a behavioural check that generating an explanation leaves every score row byte-identical.

`prompt.py` builds the (Russian, audience-tuned) chat messages from a `ScoreReport` and nothing
else; `generate_explanation.py` and `get_explanation.py` are `generateReportExplanation` and
`getReportExplanation` (`openapi.yaml`); `ports.py` holds the one score-reading Protocol this
package may depend on.
"""

from __future__ import annotations
