"""Domain exception hierarchy (HLD `10-domain-model.md` §10.1).

Every domain error subclasses `DomainError`. This module holds only the hierarchy; raising these
errors is the responsibility of the modules that own the corresponding behaviour (the state
machine for `InvalidTransitionError`, scenario validation for `ScenarioValidationError`, card
mutation for `CardFieldError`, the fact gate for `GateError`, scoring for `ScoringEvidenceError`).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error raised by `app.domain`."""


class InvalidTransitionError(DomainError):
    """Raised by `StateMachine.fire` (§10.8) when `(state, trigger)` cannot fire.

    Carries the fields a caller needs to report *what* was attempted and *why* it failed: which
    state machine (`machine`), the state it was fired from (`from_state`), the trigger name
    (`trigger`), the state it would have moved to when that is known (`to_state` — `None` when the
    `(state, trigger)` pair does not exist in the transition table at all), and the human-readable
    reason (`reason`): the pair is absent, the actor/role is not allowed, or the guard returned
    `False` (SPEC §7, §42 test 8).
    """

    def __init__(
        self,
        machine: str,
        from_state: str,
        trigger: str,
        reason: str,
        to_state: str | None = None,
    ) -> None:
        self.machine = machine
        self.from_state = from_state
        self.trigger = trigger
        self.to_state = to_state
        self.reason = reason
        super().__init__(f"{machine}: cannot fire {trigger!r} from {from_state!r}: {reason}")


class ScenarioValidationError(DomainError):
    """Raised when a `ScenarioVersion` fails load-time validation (D4, §10.4, §10.15).

    `violations` lists every rule violated, not just the first one.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__("; ".join(violations) if violations else "scenario validation failed")


class CardFieldError(DomainError):
    """Raised by `set_field` (§10.6) for an unknown `field_path` or a `value_type` mismatch."""


class GateError(DomainError):
    """Raised by the fact access gate (§10.12) on a programming-time misuse of its inputs."""


class ScoringEvidenceError(DomainError):
    """Raised when a `ScoreResult` cannot produce the evidence its rule requires — fewer than
    `max(1, rule.min_evidence)` references, or an "absence" with no bounding event (§10.14, D11,
    SPEC §42 test 11). Raised from `app.domain.scoring`, which re-exports it."""


class PrefabHandoffRequiredError(DomainError):
    """Raised by `create_session` (`session/session.py`, §10.10, D6) for a DDS-only `role_chain`
    under a policy whose `requires_prefab_handoff_for_dds_only` is true when the scenario's
    `expected_response.prefab_handoff` is absent: with no 112 stage ahead of it there is nothing
    to produce the handoff the DDS stage starts from, so the session cannot exist at all.

    `code` is the `ProblemCode` the API layer maps this to (`openapi.yaml`, `409`).
    """

    code = "PREFAB_HANDOFF_REQUIRED"

    def __init__(self, message: str = "scenario has no expected_response.prefab_handoff") -> None:
        super().__init__(message)


class RoleChainLengthError(DomainError):
    """Raised by `create_session` when `SessionPolicy.role_chain_length` is `"EXACTLY_ONE"` and
    the scenario's `role_chain` does not hold exactly one entry (§10.10).

    `openapi.yaml`'s `ProblemCode` enum is closed and has no dedicated member for this structural
    rejection, so `code` is the generic `VALIDATION_ERROR` — see this task's report, "HLD gaps".
    """

    code = "VALIDATION_ERROR"
