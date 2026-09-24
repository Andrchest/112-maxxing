"""Scripted responders and who plays each leg (HLD `70-i3-alignment.md` §70.4.5, D16; I3 E5b).

**Who plays a leg.** When the instructor binds ДДС participants to services
(`session_participants.assigned_service_id`), each leg gets its `responder` at creation
(`assign_responders`):

* its service is bound → `TRAINEE`, `bound_user_id` = that participant;
* **no** ДДС participant of the session is bound → `TRAINEE`, `bound_user_id` `NULL` (one trainee
  plays every leg — the behaviour before E5b);
* otherwise → `SCRIPTED`: nobody at the console plays this service, the scenario's script does.

**The script.** The schema-2 key `expected_response.responders` is either the literal `DEFAULT` or a
map `{<service_id>: [{after_ms, status, comment_ru, order_number}, …]}`. `after_ms` counts from the
leg's `HANDOFF_RECEIVED` (`received_at_offset_ms`); `DEFAULT` is §70.4.5's schedule
(`DEFAULT_SCRIPT`). A service the map does not name is played by `DEFAULT_SCRIPT` — a scripted leg
must end somewhere, or the memo closure (`memo_all_legs_terminal`) could never hold. Each step
names the **status** it moves to, one `SERVICE_RESPONSE_TRANSITIONS` step at a time; a leg still
`ADDED` is first moved to `RECEIVED` (`receive`, the scripted responder's first step §70.4.2 names)
at the same offset, exactly as a trainee's first status does.

**Determinism (INV 7).** `due_scripted_steps` is a pure function of the leg's status, its
`HANDOFF_RECEIVED` offset, the script and the running offset; every step is stamped with its **due**
offset (`received_at_offset_ms + after_ms`), never with the tick's. So the scripted stream is the
same whether the runner ticks every 100 ms or every 900 ms.

**INV 3.** The script is scenario data. Only stage automation (runner side) is handed it, through a
probe the composition root binds (`app.application.simulation.responder_scripts`); no DDS command
and no DDS read ever sees `responders`.

**The ДДС phone (I3 E6c, HLD 80 §80.3.3, §80.4.1, R42).** Under `dds_brigade_call: ON` the script
of a leg the trainee plays is the brigade's timeline, **voiced** by the service head on a call and
never applied. Two additive, optional keys serve it, both meaningless under `OFF` (R42): a step's
`report` (`ON_REQUEST`, the default — the head says it when asked; `CALL_IN` — the brigade calls the
ДДС to report it), and a service's `persona` override, for which a service's script may be written
as an object `{persona: <id>, steps: [...]}` instead of the bare list (`ServiceScript`). A step
written before E6c dumps exactly as before (`report` is left out while it is the default, D4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
)

from app.domain.common.ids import UserId
from app.domain.dds.assignment import DDSAssignment
from app.domain.dds.policy import StatusPolicy
from app.domain.dds.response import (
    SERVICE_RESPONSE_TRANSITIONS,
    LegResponder,
    ServiceResponseStatus,
    trigger_for,
)
from app.domain.enums import ActorType, ServiceId

__all__ = [
    "DEFAULT_RESPONDERS",
    "DEFAULT_SCRIPT",
    "ScriptReport",
    "ScriptedResponders",
    "ScriptedStep",
    "ServiceScript",
    "assign_responders",
    "due_scripted_steps",
    "persona_override_for",
    "plays_leg",
    "script_for",
    "script_problems",
    "service_scripts",
    "step_trigger",
]

DEFAULT_RESPONDERS: Literal["DEFAULT"] = "DEFAULT"
"""`expected_response.responders: DEFAULT` — every scripted leg walks `DEFAULT_SCRIPT` (R36)."""

_S = ServiceResponseStatus


class ScriptReport(str, Enum):
    """How a step reaches the ДДС under `dds_brigade_call: ON` (HLD 80 §80.3.3, I3 E6c)."""

    ON_REQUEST = "ON_REQUEST"
    """The head says it when the ДДС calls and asks (pull, REQ-1038) — the default."""
    CALL_IN = "CALL_IN"
    """The brigade calls the ДДС to report it (push): an INBOUND `DdsCall` rings when it is due."""


class ScriptedStep(BaseModel):
    """One entry of a service's script: the status the leg moves to `after_ms` after its
    `HANDOFF_RECEIVED`, with the entry's comment and «Номер наряда» (free text, A-2), and — under
    `dds_brigade_call: ON` only — how the brigade reports it (`report`, I3 E6c)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    after_ms: int = Field(ge=0)
    status: ServiceResponseStatus
    comment_ru: str | None = None
    order_number: str | None = None
    report: ScriptReport = ScriptReport.ON_REQUEST

    @model_serializer(mode="wrap")
    def _omit_default_report(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave `report` out while it is the default, so a script written before E6c dumps — and
        hashes (D4) — byte for byte as it did (P5)."""
        data = handler(self)
        if isinstance(data, dict) and data.get("report") in (ScriptReport.ON_REQUEST, "ON_REQUEST"):
            data.pop("report", None)
        return data


class ServiceScript(BaseModel):
    """A service's script with the persona that voices it (R42, I3 E6c): the object form of
    `expected_response.responders[service_id]`. The bare list stays the ordinary form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona: str | None = None
    steps: tuple[ScriptedStep, ...]


type ScriptedResponders = (
    Mapping[ServiceId, tuple[ScriptedStep, ...] | ServiceScript] | Literal["DEFAULT"]
)
"""The value of `expected_response.responders` (§70.4.5; the object form since E6c)."""

DEFAULT_SCRIPT: tuple[ScriptedStep, ...] = (
    ScriptedStep(after_ms=0, status=_S.RECEIVED),
    ScriptedStep(after_ms=15_000, status=_S.ACCEPTED),
    ScriptedStep(after_ms=60_000, status=_S.RESPONSE_STARTED),
    ScriptedStep(after_ms=180_000, status=_S.ARRIVED),
    ScriptedStep(after_ms=200_000, status=_S.WORKING),
    ScriptedStep(after_ms=600_000, status=_S.COMPLETED),
)
"""§70.4.5's `DEFAULT`: `receive +0, ACCEPTED +15 000, RESPONSE_STARTED +60 000, ARRIVED +180 000,
WORKING +200 000, COMPLETED +600 000` (ms after the leg's `HANDOFF_RECEIVED`)."""

_COMMENT_REQUIRED = frozenset({_S.NOT_ACCEPTED, _S.REFUSED})


def _steps_of(entry: tuple[ScriptedStep, ...] | ServiceScript) -> tuple[ScriptedStep, ...]:
    return entry.steps if isinstance(entry, ServiceScript) else tuple(entry)


def service_scripts(
    responders: ScriptedResponders | None,
) -> Mapping[ServiceId, tuple[ScriptedStep, ...]]:
    """Every service the map names, with its steps whichever form it was written in."""
    if responders is None or isinstance(responders, str):
        return {}
    return {service: _steps_of(entry) for service, entry in responders.items()}


def script_for(responders: ScriptedResponders | None, service_id: str) -> tuple[ScriptedStep, ...]:
    """The script a scripted leg of `service_id` walks: its own entry, else `DEFAULT_SCRIPT`.

    `None` (a scenario without the key — only a picker scenario, R36) is `DEFAULT_SCRIPT` too: a
    leg is scripted only because a participant was bound elsewhere, and it must still end.
    """
    if responders is None or isinstance(responders, str):
        return DEFAULT_SCRIPT
    entry = responders.get(ServiceId(service_id))
    return DEFAULT_SCRIPT if entry is None else _steps_of(entry)


def persona_override_for(responders: ScriptedResponders | None, service_id: str) -> str | None:
    """The scenario's persona override for `service_id` (R42), or `None`."""
    if responders is None or isinstance(responders, str):
        return None
    entry = responders.get(ServiceId(service_id))
    return entry.persona if isinstance(entry, ServiceScript) else None


def step_trigger(
    current: ServiceResponseStatus, target: ServiceResponseStatus, policy: StatusPolicy
) -> str | None:
    """The trigger a scripted (SIMULATION) step fires from `current` to `target`, or `None`.

    `current` `ADDED` is read as `RECEIVED` (the implicit `receive` fires first). A row the
    SIMULATION actor may not fire — the trainee-only correction `NOT_ACCEPTED → ACCEPTED`
    (REQ-5327) — is `None` as well.
    """
    if target is _S.RECEIVED:
        return "receive" if current is _S.ADDED else None
    source = _S.RECEIVED if current is _S.ADDED else current
    trigger = trigger_for(source, target, policy)
    if trigger is None:
        return None
    row = SERVICE_RESPONSE_TRANSITIONS[(source, trigger)]
    return trigger if ActorType.SIMULATION in row.allowed_actors else None


def script_problems(
    steps: Sequence[ScriptedStep], policy: StatusPolicy = StatusPolicy.DEFAULT
) -> list[str]:
    """Why a script cannot be played (empty when it can): each step one legal SIMULATION step of
    `SERVICE_RESPONSE_TRANSITIONS` from `ADDED` under `policy`, `after_ms` non-decreasing, a
    non-blank `comment_ru` on «Не принята» / «Отказ» (the trainee's rule, REQ-5284/5289)."""
    problems: list[str] = []
    current = _S.ADDED
    previous_after = 0
    for index, step in enumerate(steps):
        if step.after_ms < previous_after:
            problems.append(f"[{index}].after_ms {step.after_ms} is earlier than the step before")
        previous_after = step.after_ms
        if step.status in _COMMENT_REQUIRED and not (step.comment_ru or "").strip():
            problems.append(f"[{index}] status {step.status.value} needs a non-blank comment_ru")
        trigger = step_trigger(current, step.status, policy)
        if trigger is None or not _guard_allows(trigger, policy):
            problems.append(
                f"[{index}] status {step.status.value} is not one scripted step from "
                f"{current.value} (policy {policy.value})"
            )
            break
        current = step.status
    return problems


def _guard_allows(trigger: str, policy: StatusPolicy) -> bool:
    """The policy half of the leg guards (`decline`/`refuse` vs `complete_without_brigade`)."""
    if trigger in ("decline", "refuse"):
        return policy is not StatusPolicy.NO_REFUSAL
    if trigger == "complete_without_brigade":
        return policy is StatusPolicy.NO_REFUSAL
    return True


def due_scripted_steps(
    status: ServiceResponseStatus,
    received_at_offset_ms: int,
    script: Sequence[ScriptedStep],
    now_ms: int,
) -> list[tuple[ScriptedStep, int]]:
    """The steps of `script` a leg in `status` has not taken yet and that are due by `now_ms`,
    each with its due offset, in script order (see the module docstring).

    The leg's place in the script is its current status: a legal walk visits each status at most
    once (the one repeat, `NOT_ACCEPTED → ACCEPTED`, is trainee-only), so the step after the last
    one naming `status` is the next — and a leg still `ADDED` (or only implicitly `RECEIVED`)
    starts at the first step.
    """
    start = 0
    for index, step in enumerate(script):
        if step.status is status:
            start = index + 1
    due: list[tuple[ScriptedStep, int]] = []
    for step in script[start:]:
        at = received_at_offset_ms + step.after_ms
        if at > now_ms:
            break
        due.append((step, at))
    return due


def assign_responders(
    legs: Sequence[DDSAssignment], bindings: Mapping[str, UserId]
) -> tuple[DDSAssignment, ...]:
    """Each leg's `responder` and `bound_user_id` (§70.4.5; see the module docstring).

    `bindings` is `service_id → user_id` over the session's ДДС participants that are bound to a
    service. Empty ⇒ the legs are returned unchanged (`TRAINEE`, unbound).
    """
    if not bindings:
        return tuple(legs)
    return tuple(
        leg.model_copy(
            update=(
                {"responder": LegResponder.TRAINEE, "bound_user_id": bindings[leg.service_type]}
                if leg.service_type in bindings
                else {"responder": LegResponder.SCRIPTED, "bound_user_id": None}
            )
        )
        for leg in legs
    )


def plays_leg(leg: DDSAssignment, user_id: UserId) -> bool:
    """May this ДДС participant move `leg` (§70.4.5)? Its bound participant, anyone when it is
    unbound — and nobody when it is `SCRIPTED` (`guard_leg_actor_bound`'s reading)."""
    if leg.responder is LegResponder.SCRIPTED:
        return False
    return leg.bound_user_id is None or leg.bound_user_id == user_id
