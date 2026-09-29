"""The `ScenarioVersion` section models (HLD `10-domain-model.md` §10.15,
`30-scenario-format.md` §30.2-§30.7, SPEC §4-§6, §11, §12, D4).

One model per nested shape of the scenario YAML. Every model is frozen and `extra="forbid"`, so a
misspelled or unknown key anywhere in the document is a parse error (§30.8 rule 1). Field names
are copied literally from `30-scenario-format.md`.

Nothing here re-validates a cross-section rule: the thirty load-time rules of §30.8 live in
`validation.py` and run against a *parsed* document, so a single bad scenario can report every
violation it has instead of stopping at the first one. Only constraints that are purely local to
one shape (a fact id's spelling, the "exactly one key" shapes already owned by
`facts/definitions.py` and `world/conditions.py`) are enforced here.

HLD gap — `caller_profile.emotion_rules`: §10.15 types `ScenarioVersion.caller_profile` as
`CallerProfile`, but §30.3's `caller_profile` mapping carries an `emotion_rules` list, and
`CallerProfile` (§10.5, `caller/profile.py`, `extra="forbid"`) has no such field. The reading
closest to SPEC §6 ("emotion ... may change deterministically in response to events") is that the
rules are scenario data belonging to the persona, so `CallerProfileSection` *subclasses*
`CallerProfile` and adds `emotion_rules`: the §10.15 declaration stays literally true
(`isinstance(version.caller_profile, CallerProfile)`) and §30.3's YAML parses. See the task report.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from app.domain.caller.emotion import EmotionRule
from app.domain.caller.profile import CallerProfile
from app.domain.common.values import FactValue
from app.domain.dds.resources import EtaProfile, ResourceAvailability, ResourceCapability
from app.domain.dds.responders import ScriptedStep, ServiceScript
from app.domain.enums import (
    CallerVoiceStyle,
    DisclosurePolicy,
    KnowledgeState,
    ResourceType,
    ServiceId,
    ValueType,
)
from app.domain.facts.definitions import AvailableAfter
from app.domain.world.conditions import Condition

FACT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")
"""A `fact_id` is a dotted lowercase path, scenario-local (§30.2)."""


def _reject_malformed_fact_ids(fact_ids: Mapping[str, object], section: str) -> None:
    bad = sorted(key for key in fact_ids if not FACT_ID_PATTERN.match(key))
    if bad:
        raise ValueError(f"{section}: malformed fact_id(s): {', '.join(repr(k) for k in bad)}")


class WorldFactSpec(BaseModel):
    """`world_truth.facts[fact_id]` (§30.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_value: FactValue = None
    value_type: ValueType
    label_ru: str
    enum_name: str | None = None


class WorldTruthSection(BaseModel):
    """`world_truth` (§30.2). `scene_summary_ru` is instructor-only prose (D10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_summary_ru: str
    facts: Mapping[str, WorldFactSpec]

    @model_validator(mode="after")
    def _check_fact_ids(self) -> WorldTruthSection:
        _reject_malformed_fact_ids(self.facts, "world_truth.facts")
        return self


class CallerFactSpec(BaseModel):
    """`caller_knowledge.facts[fact_id]` (§30.2).

    `certainty` is deliberately *not* bounded here: §30.8 rule 9 owns the 0.0-1.0 range so that an
    out-of-range value is reported as `R09` alongside every other violation of the same file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    caller_value: FactValue = None
    knowledge: KnowledgeState
    certainty: float = 1.0


class CallerKnowledgeSection(BaseModel):
    """`caller_knowledge` (§30.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: Mapping[str, CallerFactSpec]

    @model_validator(mode="after")
    def _check_fact_ids(self) -> CallerKnowledgeSection:
        _reject_malformed_fact_ids(self.facts, "caller_knowledge.facts")
        return self


class DisclosureFactSpec(BaseModel):
    """`disclosure_rules.facts[fact_id]` (§30.2).

    `aliases_ru` and `categories` reach the interpreter LLM inside the fact catalog; values never
    do (D10) — this model carries no value-bearing field at all.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: DisclosurePolicy
    aliases_ru: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    available_after: AvailableAfter | None = None


class DisclosureRulesSection(BaseModel):
    """`disclosure_rules` (§30.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: Mapping[str, DisclosureFactSpec]

    @model_validator(mode="after")
    def _check_fact_ids(self) -> DisclosureRulesSection:
        _reject_malformed_fact_ids(self.facts, "disclosure_rules.facts")
        return self


class CallerProfileSection(CallerProfile):
    """`caller_profile` (§30.3): every `CallerProfile` field plus the scenario's `emotion_rules`.

    See the HLD-gap note at the top of this module.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    emotion_rules: tuple[EmotionRule, ...] = ()
    voice_style: CallerVoiceStyle | None = None
    """Schema 2 only (I8 V0): a closed TTS style hint (`PAIN` only) for a caller no
    `EmotionLabel` describes — the injured person calling about themselves. Read by the speech
    sink into `TtsVoiceSpec.voice_style`; R01 refuses it in a schema-1 document."""

    @model_serializer(mode="wrap")
    def _omit_absent_voice_style(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave `voice_style` out of a dump when the document has none, so every document
        written before I8 V0 dumps — and hashes (D4) — byte for byte as it did (P5)."""
        data = handler(self)
        if isinstance(data, dict) and data.get("voice_style") is None:
            data.pop("voice_style", None)
        return data


class PrefabHandoff(BaseModel):
    """`expected_response.prefab_handoff` (§30.5, D6).

    Required for a `role_chain` that starts at DDS; deliberately imperfect where the exercise
    wants it to be, so `card_values` is checked against `CARD_FIELDS` (rule 14) but never against
    world truth.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recipient_services: tuple[ServiceId, ...]
    card_values: Mapping[str, FactValue]


class ExpectedResponse(BaseModel):
    """`expected_response` (§30.5).

    `resolution_condition` is optional *in the model* so that its absence is reported as `R28`
    together with every other violation, rather than as a bare pydantic "field required".
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_services: tuple[ServiceId, ...]
    optional_services: tuple[ServiceId, ...] = ()
    required_resource_capabilities: tuple[ResourceCapability, ...] = ()
    min_units_by_service: Mapping[ServiceId, int] = Field(default_factory=dict)
    resolution_condition: Condition | None = None
    prefab_handoff: PrefabHandoff | None = None
    responders: (
        Mapping[ServiceId, tuple[ScriptedStep, ...] | ServiceScript] | Literal["DEFAULT"] | None
    ) = None
    """Schema 2 only (HLD 70 §70.4.5, I3 E5b): the scripted responders of the services no ДДС
    participant is bound to — `DEFAULT` (§70.4.5's schedule) or a script per service
    (`app.domain.dds.responders`). Rule R36 requires it when `MEMO_STATUSES` is supported; R01
    refuses it in a schema-1 document. Read at runtime by stage automation only (INV 3). Since I3
    E6c a service's script may be the object `{persona, steps}` and a step may carry `report`
    (HLD 80 §80.3.3, R42) — both for `dds_brigade_call: ON` only."""

    @model_serializer(mode="wrap")
    def _omit_absent_responders(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Leave `responders` out of a dump when the document has none, so every document written
        before E5b dumps — and hashes (D4) — byte for byte as it did (P5)."""
        data = handler(self)
        if isinstance(data, dict) and data.get("responders") is None:
            data.pop("responders", None)
        return data


class ResourceSpec(BaseModel):
    """One entry of `available_resources` (§30.4, SPEC §11).

    The scenario-file shape of `EmergencyResource` (§10.7): no `current_status` (it comes from
    `availability.initial_status` at instantiation time) and `resource_id` is the scenario-local
    string key, not the runtime `ResourceId` UUID.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    service_type: ServiceId
    resource_type: ResourceType
    callsign: str
    name_ru: str
    home_station_ru: str
    crew_size: int
    capabilities: tuple[ResourceCapability, ...]
    availability: ResourceAvailability
    eta: EtaProfile


TICKET_COUNT = 32
"""The organizer's tickets: «Билеты- задачи по C 112», 32 pages, one «БИЛЕТ» each (REQ-5203)."""
CALLS_PER_TICKET = 3
"""Each ticket's table has exactly three numbered calls (REQ-5203, REQ-5206: 96 calls in all)."""


class ProvenanceSource(str, Enum):
    """Where a scenario's content comes from (`provenance.source`)."""

    TICKET = "TICKET"
    """One call of the organizer's tickets (SRC-005, REQ-5202–REQ-5242)."""


class ScenarioProvenance(BaseModel):
    """`provenance` (schema 2 only, I3 E8; HLD 30 §30.13): the source a scenario was authored from
    and whether it is a candidate for later generation.

    Strict types: a well-formed key is rule R43's first half (a malformed one is reported as R43,
    not as a bare parse error); `ticket` / `call` in range is its second half, checked by the
    validator so it is reported with every other violation of the file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ProvenanceSource
    ticket: int = Field(strict=True)
    call: int = Field(strict=True)
    generation_candidate: bool = Field(strict=True)
