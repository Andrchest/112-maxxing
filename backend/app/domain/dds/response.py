"""`ServiceResponseStatus` and `SERVICE_RESPONSE_TRANSITIONS` — the per-leg response machine of the
ДДС memo (HLD `70-i3-alignment.md` §70.4.1, §70.4.2, D16; I3 E5a).

Every notified service (`DDSAssignment` leg) walks the memo's statuses **one step at a time**
(REQ-5293, assumption A-8): Добавлена → Получена службой → Принята / Не принята → Начало
реагирования → Прибытие → Проведение работ → Работы завершены | Отказ от выполнения работ. The
table below copies §70.4.2 row for row; the `DDSStageState` machine is untouched
(`session/transitions.py`).

Two readings of the §70.4.2 table, stated once:

* **two guards in one cell.** `decline` and `refuse` name `guard_comment_present` *and*
  `guard_policy_allows_refusal`; `Transition` holds one `guard_name`, so those rows carry the
  conjunction `guard_comment_present_and_policy_allows_refusal`, registered below beside its two
  halves. The application checks the comment first and answers `422 COMMENT_REQUIRED` (the
  contract's code), so the guard's comment half only ever denies a caller that bypassed that check;
* **the guard's facts.** A leg guard needs the service's status policy and the comment of the
  command, neither of which the leg holds. `LegGuardSubject` carries the three facts and rides in
  `GuardContext.assignment`, which is `Any` for exactly this kind of role-specific subject.

`TERMINAL_RESPONSE_STATUSES` is the machine's own terminal set (`COMPLETED`, `REFUSED`).
`CLOSABLE_RESPONSE_STATUSES` is the memo closure's (`memo_all_legs_terminal`, §70.4.4): it also
counts `NOT_ACCEPTED`, which the machine still lets a trainee correct (REQ-5327) but which ends that
service's part in the incident.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import UserId
from app.domain.common.state_machine import GuardContext, StateMachine, Transition, TransitionTable
from app.domain.dds.policy import StatusPolicy, allows_refusal
from app.domain.enums import ActorType
from app.domain.events.types import EventType

__all__ = [
    "CLOSABLE_RESPONSE_STATUSES",
    "PRIMARY_DECISIONS",
    "SERVICE_RESPONSE_GUARDS",
    "SERVICE_RESPONSE_LABELS_RU",
    "SERVICE_RESPONSE_MACHINE",
    "SERVICE_RESPONSE_TRANSITIONS",
    "TERMINAL_RESPONSE_STATUSES",
    "TRIGGER_LABELS_RU",
    "CompletionReason",
    "LegGuardSubject",
    "LegResponder",
    "ServiceResponseStatus",
    "StatusSource",
    "trigger_for",
]


class ServiceResponseStatus(str, Enum):
    """The memo's per-service statuses (p.21–22, REQ-5281–5289), §70.4.1."""

    ADDED = "ADDED"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    NOT_ACCEPTED = "NOT_ACCEPTED"
    RESPONSE_STARTED = "RESPONSE_STARTED"
    ARRIVED = "ARRIVED"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"


SERVICE_RESPONSE_LABELS_RU: Mapping[ServiceResponseStatus, str] = {
    ServiceResponseStatus.ADDED: "Добавлена",
    ServiceResponseStatus.RECEIVED: "Получена службой",
    ServiceResponseStatus.ACCEPTED: "Принята",
    ServiceResponseStatus.NOT_ACCEPTED: "Не принята",
    ServiceResponseStatus.RESPONSE_STARTED: "Начало реагирования",
    ServiceResponseStatus.ARRIVED: "Прибытие",
    ServiceResponseStatus.WORKING: "Проведение работ",
    ServiceResponseStatus.COMPLETED: "Работы завершены",
    ServiceResponseStatus.REFUSED: "Отказ от выполнения работ",
}
"""The memo's labels, verbatim (§70.4.1)."""


class LegResponder(str, Enum):
    """Who plays a leg (§70.4.3, §70.4.5; `SCRIPTED` since E5b, `dds/responders.py`)."""

    TRAINEE = "TRAINEE"
    SCRIPTED = "SCRIPTED"


class StatusSource(str, Enum):
    """`DDS_SERVICE_STATUS_SET.source` (§70.7)."""

    TRAINEE = "TRAINEE"
    SCRIPTED_RESPONDER = "SCRIPTED_RESPONDER"
    PICKER_MIRROR = "PICKER_MIRROR"
    SYSTEM = "SYSTEM"


class CompletionReason(str, Enum):
    """`DDS_SERVICE_STATUS_SET.completion_reason`: 103 completes without a brigade (REQ-5290)."""

    WITHOUT_BRIGADE = "WITHOUT_BRIGADE"


TERMINAL_RESPONSE_STATUSES: frozenset[ServiceResponseStatus] = frozenset(
    {ServiceResponseStatus.COMPLETED, ServiceResponseStatus.REFUSED}
)
"""The machine's terminal statuses — no row leaves them."""

CLOSABLE_RESPONSE_STATUSES: frozenset[ServiceResponseStatus] = frozenset(
    {
        ServiceResponseStatus.COMPLETED,
        ServiceResponseStatus.NOT_ACCEPTED,
        ServiceResponseStatus.REFUSED,
    }
)
"""`memo_all_legs_terminal` (§70.4.4): Работы завершены, Не принята, Отказ от выполнения работ."""

PRIMARY_DECISIONS: frozenset[ServiceResponseStatus] = frozenset(
    {ServiceResponseStatus.ACCEPTED, ServiceResponseStatus.NOT_ACCEPTED}
)
"""The competence decision (Принята / Не принята, always on — C1)."""


class LegGuardSubject(BaseModel):
    """What a leg guard reads, carried in `GuardContext.assignment` (see the module docstring)."""

    model_config = ConfigDict(frozen=True)

    status_policy: StatusPolicy = StatusPolicy.DEFAULT
    comment_ru: str | None = None
    bound_user_id: UserId | None = None
    """`None` = any ДДС participant plays the leg (§70.4.5) — unless the leg is `SCRIPTED`."""
    responder: LegResponder = LegResponder.TRAINEE
    """A `SCRIPTED` leg is played by the scenario's script alone (§70.4.5, I3 E5b)."""


# ---------------------------------------------------------------------------------------------
# The table (§70.4.2)
# ---------------------------------------------------------------------------------------------

_S = ServiceResponseStatus
_SIMULATION = frozenset({ActorType.SIMULATION})
_TRAINEE = frozenset({ActorType.TRAINEE})
_TRAINEE_OR_SIMULATION = frozenset({ActorType.TRAINEE, ActorType.SIMULATION})
_REFUSAL_GUARD = "guard_comment_present_and_policy_allows_refusal"
_SET = EventType.DDS_SERVICE_STATUS_SET

_RESPONSE_ROWS: tuple[Transition[ServiceResponseStatus], ...] = (
    Transition(
        source=_S.ADDED,
        trigger="receive",
        target=_S.RECEIVED,
        allowed_actors=_SIMULATION,
        emits=_SET,
    ),
    Transition(
        source=_S.RECEIVED,
        trigger="accept",
        target=_S.ACCEPTED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        guard_name="guard_leg_actor_bound",
        emits=_SET,
    ),
    Transition(
        source=_S.RECEIVED,
        trigger="decline",
        target=_S.NOT_ACCEPTED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        guard_name=_REFUSAL_GUARD,
        emits=_SET,
    ),
    Transition(
        source=_S.NOT_ACCEPTED,
        trigger="accept",
        target=_S.ACCEPTED,
        allowed_actors=_TRAINEE,
        emits=_SET,
    ),
    Transition(
        source=_S.ACCEPTED,
        trigger="start_response",
        target=_S.RESPONSE_STARTED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        emits=_SET,
    ),
    Transition(
        source=_S.RESPONSE_STARTED,
        trigger="arrive",
        target=_S.ARRIVED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        emits=_SET,
    ),
    Transition(
        source=_S.ARRIVED,
        trigger="start_work",
        target=_S.WORKING,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        emits=_SET,
    ),
    Transition(
        source=_S.WORKING,
        trigger="complete",
        target=_S.COMPLETED,
        allowed_actors=_TRAINEE_OR_SIMULATION,
        emits=_SET,
    ),
    *(
        Transition(
            source=source,
            trigger="refuse",
            target=_S.REFUSED,
            allowed_actors=_TRAINEE_OR_SIMULATION,
            guard_name=_REFUSAL_GUARD,
            emits=_SET,
        )
        for source in (_S.ACCEPTED, _S.RESPONSE_STARTED, _S.ARRIVED, _S.WORKING)
    ),
    *(
        Transition(
            source=source,
            trigger="complete_without_brigade",
            target=_S.COMPLETED,
            allowed_actors=_TRAINEE_OR_SIMULATION,
            guard_name="guard_policy_is_no_refusal",
            emits=_SET,
        )
        for source in (_S.RECEIVED, _S.ACCEPTED, _S.RESPONSE_STARTED, _S.ARRIVED, _S.WORKING)
    ),
)

SERVICE_RESPONSE_TRANSITIONS: TransitionTable[ServiceResponseStatus] = {
    (row.source, row.trigger): row for row in _RESPONSE_ROWS
}

TRIGGER_LABELS_RU: Mapping[str, str] = {
    "receive": SERVICE_RESPONSE_LABELS_RU[_S.RECEIVED],
    "accept": SERVICE_RESPONSE_LABELS_RU[_S.ACCEPTED],
    "decline": SERVICE_RESPONSE_LABELS_RU[_S.NOT_ACCEPTED],
    "start_response": SERVICE_RESPONSE_LABELS_RU[_S.RESPONSE_STARTED],
    "arrive": SERVICE_RESPONSE_LABELS_RU[_S.ARRIVED],
    "start_work": SERVICE_RESPONSE_LABELS_RU[_S.WORKING],
    "complete": SERVICE_RESPONSE_LABELS_RU[_S.COMPLETED],
    "refuse": SERVICE_RESPONSE_LABELS_RU[_S.REFUSED],
    "complete_without_brigade": "Работы завершены (без бригады)",
}
"""The pencil's dropdown: each trigger is shown as the status it leads to (REQ-5292)."""


# ---------------------------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------------------------


def _subject(ctx: GuardContext) -> LegGuardSubject:
    subject = ctx.assignment
    return subject if isinstance(subject, LegGuardSubject) else LegGuardSubject()


def guard_leg_actor_bound(ctx: GuardContext) -> bool:
    """§70.4.5: a trainee command must come from the leg's `bound_user_id`, or — when the leg is
    unbound — from any ДДС participant (the application's gate has already checked that). A
    `SCRIPTED` leg answers no trainee at all: its service has no bound participant, the scenario's
    script plays it (I3 E5b). A SIMULATION actor (scripted responder, picker mirror) plays the leg
    by construction."""
    if ctx.actor.actor_type is not ActorType.TRAINEE:
        return True
    subject = _subject(ctx)
    if subject.responder is LegResponder.SCRIPTED:
        return False
    bound = subject.bound_user_id
    return bound is None or ctx.actor.actor_id == bound


def guard_comment_present(ctx: GuardContext) -> bool:
    """«Не принята» and «Отказ» need a non-blank comment (REQ-5284, REQ-5289; A-9)."""
    comment = _subject(ctx).comment_ru
    return comment is not None and comment.strip() != ""


def guard_policy_allows_refusal(ctx: GuardContext) -> bool:
    """The 103 policy `NO_REFUSAL` replaces `decline`/`refuse` (REQ-5290)."""
    return allows_refusal(_subject(ctx).status_policy)


def guard_comment_present_and_policy_allows_refusal(ctx: GuardContext) -> bool:
    """`decline` / `refuse`: both §70.4.2 guards of the cell."""
    return guard_comment_present(ctx) and guard_policy_allows_refusal(ctx)


def guard_policy_is_no_refusal(ctx: GuardContext) -> bool:
    """`complete_without_brigade` exists only under the 103 policy."""
    return not allows_refusal(_subject(ctx).status_policy)


SERVICE_RESPONSE_GUARDS: Mapping[str, Callable[[GuardContext], bool]] = {
    "guard_leg_actor_bound": guard_leg_actor_bound,
    _REFUSAL_GUARD: guard_comment_present_and_policy_allows_refusal,
    "guard_policy_is_no_refusal": guard_policy_is_no_refusal,
}

SERVICE_RESPONSE_MACHINE: StateMachine[ServiceResponseStatus] = StateMachine(
    SERVICE_RESPONSE_TRANSITIONS, SERVICE_RESPONSE_GUARDS
)


def trigger_for(
    current: ServiceResponseStatus, target: ServiceResponseStatus, policy: StatusPolicy
) -> str | None:
    """The one trigger that takes `current` to `target`, or `None` (an out-of-sequence status).

    `COMPLETED` is `complete` from `WORKING` and `complete_without_brigade` from any earlier status
    under `NO_REFUSAL` (`SetServiceStatusRequest.status`, §70.4.2). A trigger whose guard would
    deny is still returned — the machine decides, so the refusal is the ordinary `409`.
    """
    if target is ServiceResponseStatus.COMPLETED and current is not ServiceResponseStatus.WORKING:
        if policy is StatusPolicy.NO_REFUSAL:
            key = (current, "complete_without_brigade")
            return "complete_without_brigade" if key in SERVICE_RESPONSE_TRANSITIONS else None
        return None
    for (source, trigger), row in SERVICE_RESPONSE_TRANSITIONS.items():
        if source is current and row.target is target and trigger != "complete_without_brigade":
            return trigger
    return None
