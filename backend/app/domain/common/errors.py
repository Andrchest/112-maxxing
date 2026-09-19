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
    """Raised when a `ScoreResult` with a nonzero `points_awarded` has zero evidence (§10.14)."""
