"""Domain errors the explanation slice raises (SPEC §2, §29; R1, R8; `openapi.yaml`).

Each mirrors a `ProblemCode` already mapped in `app.api.errors.STATUS_BY_CODE`
(`REPORT_NOT_READY` 409, `EXPLANATION_ALREADY_EXISTS` 409, `LLM_UNAVAILABLE` 503) — defined again
here rather than imported from `app.application.scoring.rescore_session.ReportNotReadyError`,
because this package may not mention `rescore_session` or `score_session` at all, by name, in any
form (R8's structural guarantee — see `backend/tests/invariants/
test_explanation_cannot_write_scores.py`'s part (a), which scans for exactly that identifier).
Two Python classes sharing one `code` string map to the same HTTP response either way:
`app.api.errors.code_of` looks the string up on the raised instance, not the class that raised it.
"""

from __future__ import annotations

from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.enums import SessionState

__all__ = [
    "ExplanationAlreadyExistsError",
    "ExplanationLLMUnavailableError",
    "ReportNotReadyError",
]


class ReportNotReadyError(DomainError):
    """No stored score for this session, or the session has not reached `COMPLETED`
    (`409 REPORT_NOT_READY`) — "report for an unfinished session refused" is this epic's own
    invariant (R1), and it holds for the explanation exactly as it does for the report itself."""

    code = "REPORT_NOT_READY"

    def __init__(self, session_id: SessionId, state: SessionState) -> None:
        self.session_id = session_id
        self.state = state
        super().__init__(
            f"session {session_id} is {state.value}, not COMPLETED with stored scores; "
            "nothing to explain"
        )


class ExplanationAlreadyExistsError(DomainError):
    """A stored explanation already exists for `(session_id, audience)` and `regenerate` was not
    set (`409 EXPLANATION_ALREADY_EXISTS`, DO item 2)."""

    code = "EXPLANATION_ALREADY_EXISTS"

    def __init__(self, session_id: SessionId, audience: str) -> None:
        self.session_id = session_id
        self.audience = audience
        super().__init__(
            f"session {session_id} already has a {audience} explanation; pass "
            "regenerate=true to replace it"
        )


class ExplanationLLMUnavailableError(DomainError):
    """The LLM timed out, was unreachable, or answered with no usable text
    (`503 LLM_UNAVAILABLE`, DO item 2). Nothing is stored; the report itself, which never depends
    on this call, is unaffected (SPEC §26, §41)."""

    code = "LLM_UNAVAILABLE"

    def __init__(self, session_id: SessionId, reason: str) -> None:
        self.session_id = session_id
        self.reason = reason
        super().__init__(f"session {session_id}: explanation LLM unavailable: {reason}")
