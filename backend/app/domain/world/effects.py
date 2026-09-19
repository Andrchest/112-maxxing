"""World-event effects (HLD `10-domain-model.md` §10.11, `30-scenario-format.md` §30.6.4).

The seven effect models named in the HLD effects table, discriminated on `kind: EffectKind`. All
Pydantic v2, `extra="forbid"`, frozen. Field names and defaults are copied literally from the HLD
table: a field the table shows with no `= ...` is required (nullable types still require an
explicit value, matching the YAML shapes in §30.6.4).

Applying an effect to a `WorldState` is out of scope for this slice (E6, `world/engine.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.values import FactValue
from app.domain.enums import (
    EffectKind,
    EmotionLabel,
    KnowledgeState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
)


class CallerFactChange(BaseModel):
    """One fact's new caller-belief value inside a `MutateCallerBelief` effect (§10.11)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: FactValue
    knowledge: KnowledgeState
    certainty: float = Field(ge=0.0, le=1.0)


class MutateWorldTruth(BaseModel):
    """`{kind: MUTATE_WORLD_TRUTH, changes: {fact_id: new_value}}` (§30.6.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.MUTATE_WORLD_TRUTH] = EffectKind.MUTATE_WORLD_TRUTH
    changes: Mapping[str, FactValue]


class MutateCallerBelief(BaseModel):
    """Applied only if the owning event has `caller_observable = true` (D7).

    Dropped with no trace by `advance` (E6) when that flag is false; this model itself imposes no
    such restriction — it only describes the shape.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.MUTATE_CALLER_BELIEF] = EffectKind.MUTATE_CALLER_BELIEF
    changes: Mapping[str, CallerFactChange]


class CreateNotification(BaseModel):
    """`{kind: CREATE_NOTIFICATION, audience_role, severity, title_ru, body_ru}` (§30.6.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.CREATE_NOTIFICATION] = EffectKind.CREATE_NOTIFICATION
    audience_role: RoleType
    severity: NotificationSeverity
    title_ru: str
    body_ru: str


class CreateRadioMessage(BaseModel):
    """`{kind: CREATE_RADIO_MESSAGE, from_callsign, to_role, text_ru, resource_id}` (§30.6.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.CREATE_RADIO_MESSAGE] = EffectKind.CREATE_RADIO_MESSAGE
    from_callsign: str
    to_role: RoleType
    text_ru: str
    resource_id: str | None


class AlterResourceAvailability(BaseModel):
    """`{kind: ALTER_RESOURCE_AVAILABILITY, resource_id, new_status, restore, eta_multiplier}`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.ALTER_RESOURCE_AVAILABILITY] = EffectKind.ALTER_RESOURCE_AVAILABILITY
    resource_id: str
    new_status: ResourceStatus
    restore: bool = False
    eta_multiplier: float = 1.0


class TriggerEvent(BaseModel):
    """`{kind: TRIGGER_EVENT, world_event_id, delay_ms}` (§30.6.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.TRIGGER_EVENT] = EffectKind.TRIGGER_EVENT
    world_event_id: str
    delay_ms: int = 0


class ChangeCallerEmotion(BaseModel):
    """`{kind: CHANGE_CALLER_EMOTION, set_emotion, stress_delta}` (§30.6.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[EffectKind.CHANGE_CALLER_EMOTION] = EffectKind.CHANGE_CALLER_EMOTION
    set_emotion: EmotionLabel | None
    stress_delta: float = 0.0


Effect = Annotated[
    MutateWorldTruth
    | MutateCallerBelief
    | CreateNotification
    | CreateRadioMessage
    | AlterResourceAvailability
    | TriggerEvent
    | ChangeCallerEmotion,
    Field(discriminator="kind"),
]
