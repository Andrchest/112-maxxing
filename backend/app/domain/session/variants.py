"""Variant switches — `SessionVariants` and its three homes (HLD `70-i3-alignment.md` §70.2,
§70.11, D14).

Four switches, one frozen value object:

* `card_source` — `GENERATED_CARD` (no caller: the card arrives generated as the scenario's prefab
  handoff and the chain starts at DDS) or `CALLER_VOICE` (today's AI-voiced caller and 112
  interview; frozen but kept, owner decision);
* `dds_mode` — `RESOURCE_PICKER` (today's resource board) or `MEMO_STATUSES` (E5);
* `dds_card_check` — `OFF` or `ON` (E5);
* `dds_brigade_call` — `OFF` or `ON` (H2 → E6).

The three homes and their precedence (§70.2.2, no fourth): the scenario declares *supported +
default* (`ScenarioVariants`; a schema-1 document has none and gets `derive_scenario_variants`),
session creation *selects* (`resolve_variants`: request value → scenario default), and
`SESSION_CREATED.variants` plus `simulation_sessions.variants` *record* the result. A value outside
`IMPLEMENTED_VARIANT_VALUES` is `409 VARIANT_NOT_AVAILABLE` and is checked first; a value outside
the scenario's `supported` is `409 VARIANT_NOT_SUPPORTED`.

This module imports nothing from `app.domain.scenario`: `scenario/version.py` imports it (the
schema-2 key `variants` is a `ScenarioVariants`), so the derivation takes the three facts it needs
as arguments instead of a `ScenarioVersion`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.domain.common.errors import DomainError
from app.domain.enums import RoleType

__all__ = [
    "IMPLEMENTED_VARIANT_VALUES",
    "PRODUCT_DEFAULT_VARIANTS",
    "SWITCHES",
    "SWITCH_ENUMS",
    "CardSource",
    "DdsBrigadeCall",
    "DdsCardCheck",
    "DdsMode",
    "PartialVariants",
    "ScenarioVariants",
    "SessionVariants",
    "VariantNotAvailableError",
    "VariantNotSupportedError",
    "VariantSupport",
    "available_scenario_variants",
    "derive_scenario_variants",
    "effective_role_chain",
    "legacy_session_variants",
    "resolve_variants",
    "variants_payload",
]


class CardSource(str, Enum):
    GENERATED_CARD = "GENERATED_CARD"
    """No caller: the card arrives generated (prefab); the chain starts at DDS."""
    CALLER_VOICE = "CALLER_VOICE"
    """Today's AI-voiced caller + 112 interview; FROZEN, kept (owner)."""


class DdsMode(str, Enum):
    MEMO_STATUSES = "MEMO_STATUSES"
    """Per-service statuses of the ДДС memo (F3) — exists from E5."""
    RESOURCE_PICKER = "RESOURCE_PICKER"
    """Today's resource board + dispatch."""


class DdsCardCheck(str, Enum):
    OFF = "OFF"
    """ДДС does not check the 112 card (customer 23.09, REQ-5915)."""
    ON = "ON"
    """ДДС may flag card issues (msg638 reading) — exists from E5."""


class DdsBrigadeCall(str, Enum):
    OFF = "OFF"
    ON = "ON"
    """ДДС ↔ brigade voice call — exists from H2/E6."""


SWITCHES: tuple[str, ...] = ("card_source", "dds_mode", "dds_card_check", "dds_brigade_call")
"""The `SessionVariants` field names, in declaration order."""

SWITCH_ENUMS: Mapping[str, type[Enum]] = {
    "card_source": CardSource,
    "dds_mode": DdsMode,
    "dds_card_check": DdsCardCheck,
    "dds_brigade_call": DdsBrigadeCall,
}
"""Each switch's value enum — what rule R40 checks `applies_to_variants` against."""


class SessionVariants(BaseModel):
    """The resolved, recorded variants of one session; immutable after creation (§70.2.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_source: CardSource
    dds_mode: DdsMode
    dds_card_check: DdsCardCheck
    dds_brigade_call: DdsBrigadeCall


class PartialVariants(BaseModel):
    """A request for variants: every switch optional (`VariantsRequest`, §70.2.2 home 2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_source: CardSource | None = None
    dds_mode: DdsMode | None = None
    dds_card_check: DdsCardCheck | None = None
    dds_brigade_call: DdsBrigadeCall | None = None


class VariantSupport(BaseModel):
    """What a scenario supports per switch.

    Every tuple is non-empty and duplicate-free — rule R32 checks that, so that a violation is
    reported with every other one instead of as a bare parse error.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_source: tuple[CardSource, ...]
    dds_mode: tuple[DdsMode, ...]
    dds_card_check: tuple[DdsCardCheck, ...]
    dds_brigade_call: tuple[DdsBrigadeCall, ...]


class ScenarioVariants(BaseModel):
    """The schema-2 scenario key `variants` (§70.2.2 home 1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: VariantSupport
    default: SessionVariants


PRODUCT_DEFAULT_VARIANTS = SessionVariants(
    card_source=CardSource.GENERATED_CARD,
    dds_mode=DdsMode.MEMO_STATUSES,
    dds_card_check=DdsCardCheck.OFF,
    dds_brigade_call=DdsBrigadeCall.OFF,
)
"""The switch matrix's product default from E5 (§70.11): `GENERATED_CARD` and `MEMO_STATUSES` for
schema 2, card check `OFF`, brigade call `OFF`. It applies only where a schema-2 document's
derived support allows it (`derive_scenario_variants`); schema 1 keeps `RESOURCE_PICKER` forever
(P5)."""

IMPLEMENTED_VARIANT_VALUES: Mapping[str, frozenset[str]] = {
    "card_source": frozenset({CardSource.CALLER_VOICE.value, CardSource.GENERATED_CARD.value}),
    "dds_mode": frozenset({DdsMode.RESOURCE_PICKER.value, DdsMode.MEMO_STATUSES.value}),
    "dds_card_check": frozenset({DdsCardCheck.OFF.value, DdsCardCheck.ON.value}),
    "dds_brigade_call": frozenset({DdsBrigadeCall.OFF.value, DdsBrigadeCall.ON.value}),
}
"""What the product can run today; grows per epic (§70.11): E5a added `MEMO_STATUSES`, E5b card
check `ON` («Отметить ошибку в карточке», `flagDdsCardIssue`), E6b brigade call `ON` — "the ДДС
has a phone", memo mode only (HLD 80 §80.5, D25, R41). Memo scenarios declare `ON` as their default
(D28, owner 2026-09-25, superseding C7); the derived default above stays `OFF` because a derived
support is picker-only and never contains `ON`."""


class VariantNotAvailableError(DomainError):
    """A requested or defaulted value is outside `IMPLEMENTED_VARIANT_VALUES` (`409`)."""

    code = "VARIANT_NOT_AVAILABLE"

    def __init__(self, switch: str, value: str) -> None:
        self.switch = switch
        self.value = value
        super().__init__(f"variant {switch}={value} is not available in this build")


class VariantNotSupportedError(DomainError):
    """A requested value is outside the scenario's `variants.supported` (`409`)."""

    code = "VARIANT_NOT_SUPPORTED"

    def __init__(self, switch: str, value: str) -> None:
        self.switch = switch
        self.value = value
        super().__init__(f"variant {switch}={value} is not supported by this scenario version")


# ---------------------------------------------------------------------------------------------
# Derivation (schema 1, and schema 2 without the `variants` key)
# ---------------------------------------------------------------------------------------------


def derive_scenario_variants(
    *,
    schema_version: int,
    role_chain: Sequence[RoleType],
    has_prefab_handoff: bool,
    declared: ScenarioVariants | None = None,
) -> ScenarioVariants:
    """A scenario version's `ScenarioVariants` (§70.2.2 home 1).

    A declared `variants` key is returned as written. Otherwise the support is derived (P5):
    `CALLER_VOICE` iff `OPERATOR_112 ∈ role_chain`, `GENERATED_CARD` iff a prefab handoff is
    present (or the chain starts at DDS, which rule R29 ties to a prefab anyway); `dds_mode`
    `{RESOURCE_PICKER}`; `dds_card_check` `{OFF, ON}`; `dds_brigade_call` `{OFF}`. The schema-1
    default is `CALLER_VOICE` when supported (today's behaviour), else `GENERATED_CARD`, then
    `RESOURCE_PICKER`, `OFF`, `OFF`. A schema-2 document without the key takes
    `PRODUCT_DEFAULT_VARIANTS` wherever the derived support allows it.
    """
    if declared is not None:
        return declared
    card_sources: list[CardSource] = []
    if RoleType.OPERATOR_112 in role_chain:
        card_sources.append(CardSource.CALLER_VOICE)
    # A chain that starts at DDS is run on its generated card by construction; rule R29 makes
    # its prefab mandatory, and a document breaking R29 must still fail where it fails today
    # (`PrefabHandoffRequiredError` at creation, P5) rather than as an unsupported variant.
    if has_prefab_handoff or (role_chain and role_chain[0] is RoleType.DDS):
        card_sources.append(CardSource.GENERATED_CARD)
    supported = VariantSupport(
        card_source=tuple(card_sources),
        dds_mode=(DdsMode.RESOURCE_PICKER,),
        dds_card_check=(DdsCardCheck.OFF, DdsCardCheck.ON),
        dds_brigade_call=(DdsBrigadeCall.OFF,),
    )
    schema_1_default = SessionVariants(
        card_source=card_sources[0] if card_sources else CardSource.GENERATED_CARD,
        dds_mode=DdsMode.RESOURCE_PICKER,
        dds_card_check=DdsCardCheck.OFF,
        dds_brigade_call=DdsBrigadeCall.OFF,
    )
    if schema_version < 2:
        return ScenarioVariants(supported=supported, default=schema_1_default)
    default = {
        switch: (
            getattr(PRODUCT_DEFAULT_VARIANTS, switch)
            if getattr(PRODUCT_DEFAULT_VARIANTS, switch) in getattr(supported, switch)
            else getattr(schema_1_default, switch)
        )
        for switch in SWITCHES
    }
    return ScenarioVariants(supported=supported, default=SessionVariants(**default))


def legacy_session_variants(role_chain: Sequence[RoleType]) -> SessionVariants:
    """What a session recorded before E1 ran as (`simulation_sessions.variants = '{}'`).

    Before E1 a session's stages were exactly its scenario's `role_chain`, so the schema-1
    derived default can be read off the session's own chain: `CALLER_VOICE` when an
    `OPERATOR_112` stage exists, else `GENERATED_CARD` (a `[DDS]` chain run on its prefab).
    """
    return derive_scenario_variants(
        schema_version=1, role_chain=role_chain, has_prefab_handoff=False
    ).default


def available_scenario_variants(
    scenario: ScenarioVariants,
    implemented: Mapping[str, frozenset[str]] = IMPLEMENTED_VARIANT_VALUES,
) -> ScenarioVariants:
    """`ScenarioVariantsView`: the support after the implemented-values filter.

    A switch whose every supported value is unimplemented keeps its declared support (the view
    requires a non-empty list; creating a session on it answers `409 VARIANT_NOT_AVAILABLE`). The
    default moves to the first remaining supported value when the declared one is filtered out.
    """
    supported: dict[str, tuple[Enum, ...]] = {}
    default: dict[str, Enum] = {}
    for switch in SWITCHES:
        declared: tuple[Enum, ...] = getattr(scenario.supported, switch)
        kept = tuple(value for value in declared if value.value in implemented.get(switch, ()))
        supported[switch] = kept or declared
        declared_default: Enum = getattr(scenario.default, switch)
        default[switch] = (
            declared_default if declared_default in supported[switch] else supported[switch][0]
        )
    return ScenarioVariants(
        supported=VariantSupport.model_validate(supported),
        default=SessionVariants.model_validate(default),
    )


# ---------------------------------------------------------------------------------------------
# Resolution (session creation) and its consequences
# ---------------------------------------------------------------------------------------------


def resolve_variants(
    requested: PartialVariants,
    scenario: ScenarioVariants,
    implemented: Mapping[str, frozenset[str]] = IMPLEMENTED_VARIANT_VALUES,
) -> SessionVariants:
    """Resolve per switch: request value → scenario default (§70.2.2 home 2).

    The implemented-values check runs over all four switches before the support check, so an
    unimplemented value never reaches content validation. A resolution to `dds_brigade_call: ON`
    with `dds_mode: RESOURCE_PICKER` is `VARIANT_NOT_SUPPORTED` (R41, I3 E6b) — unless `ON` came
    from the scenario default and was not requested: the phone is a memo-mode default (D28), so a
    picker session that names no phone value runs with `OFF`.
    """
    chosen: dict[str, Enum] = {}
    for switch in SWITCHES:
        value: Enum | None = getattr(requested, switch)
        chosen[switch] = value if value is not None else getattr(scenario.default, switch)
    if (
        requested.dds_brigade_call is None
        and chosen["dds_brigade_call"] is DdsBrigadeCall.ON
        and chosen["dds_mode"] is DdsMode.RESOURCE_PICKER
    ):
        # D28 (owner 2026-09-25): `ON` is the default of memo scenarios only (R41).
        chosen["dds_brigade_call"] = DdsBrigadeCall.OFF
    for switch in SWITCHES:
        if chosen[switch].value not in implemented.get(switch, ()):
            raise VariantNotAvailableError(switch, chosen[switch].value)
    for switch in SWITCHES:
        if chosen[switch] not in getattr(scenario.supported, switch):
            raise VariantNotSupportedError(switch, chosen[switch].value)
    if (
        chosen["dds_brigade_call"] is DdsBrigadeCall.ON
        and chosen["dds_mode"] is DdsMode.RESOURCE_PICKER
    ):
        # R41 (I3 E6b, HLD 80 §80.5): the ДДС phone exists in memo mode only.
        raise VariantNotSupportedError("dds_brigade_call", DdsBrigadeCall.ON.value)
    return SessionVariants.model_validate(chosen)


def effective_role_chain(
    role_chain: Sequence[RoleType], card_source: CardSource
) -> tuple[RoleType, ...]:
    """The chain a session actually runs (§70.2.4 "Flow").

    `CALLER_VOICE` runs the scenario's whole chain; `GENERATED_CARD` runs the suffix starting at
    DDS — empty when the chain has no DDS stage, which the caller refuses.
    """
    chain = tuple(role_chain)
    if card_source is CardSource.CALLER_VOICE:
        return chain
    if RoleType.DDS not in chain:
        return ()
    return chain[chain.index(RoleType.DDS) :]


def variants_payload(variants: SessionVariants) -> dict[str, str]:
    """`SESSION_CREATED.variants` / `simulation_sessions.variants`: switch → value string."""
    return {switch: getattr(variants, switch).value for switch in SWITCHES}
