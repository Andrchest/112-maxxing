"""Variant switches (HLD `70-i3-alignment.md` §70.2, §70.11, D14): the value objects, the
schema-1 derivation, `resolve_variants`' precedence and its two refusals, the effective role chain,
and what `create_session` records.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.domain.enums import RoleType, SessionMode
from app.domain.events.catalog import validate_payload
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession, create_session
from app.domain.session.variants import (
    IMPLEMENTED_VARIANT_VALUES,
    PRODUCT_DEFAULT_VARIANTS,
    CardSource,
    DdsBrigadeCall,
    DdsCardCheck,
    DdsMode,
    PartialVariants,
    ScenarioVariants,
    SessionVariants,
    VariantNotAvailableError,
    VariantNotSupportedError,
    VariantSupport,
    available_scenario_variants,
    derive_scenario_variants,
    effective_role_chain,
    legacy_session_variants,
    resolve_variants,
)

from tests.unit.domain.session import _builders as b

OP = RoleType.OPERATOR_112
DDS = RoleType.DDS

ALL_SUPPORTED = ScenarioVariants(
    supported=VariantSupport(
        card_source=(CardSource.CALLER_VOICE, CardSource.GENERATED_CARD),
        dds_mode=(DdsMode.RESOURCE_PICKER, DdsMode.MEMO_STATUSES),
        dds_card_check=(DdsCardCheck.OFF, DdsCardCheck.ON),
        dds_brigade_call=(DdsBrigadeCall.OFF, DdsBrigadeCall.ON),
    ),
    default=PRODUCT_DEFAULT_VARIANTS,
)


# ---------------------------------------------------------------------------------------------
# The switch matrix (§70.11) after E5a
# ---------------------------------------------------------------------------------------------


def test_product_default_is_the_owner_default_from_e5() -> None:
    """§70.11 "Product default from E5": `MEMO_STATUSES` (schema 2); was `RESOURCE_PICKER`."""
    expected = SessionVariants(
        card_source=CardSource.GENERATED_CARD,
        dds_mode=DdsMode.MEMO_STATUSES,
        dds_card_check=DdsCardCheck.OFF,
        dds_brigade_call=DdsBrigadeCall.OFF,
    )
    assert expected == PRODUCT_DEFAULT_VARIANTS


def test_implemented_values_after_e5a() -> None:
    expected = {
        "card_source": frozenset({"CALLER_VOICE", "GENERATED_CARD"}),
        "dds_mode": frozenset({"RESOURCE_PICKER", "MEMO_STATUSES"}),
        "dds_card_check": frozenset({"OFF"}),
        "dds_brigade_call": frozenset({"OFF"}),
    }
    assert expected == IMPLEMENTED_VARIANT_VALUES


# ---------------------------------------------------------------------------------------------
# Derivation (§70.2.2 home 1)
# ---------------------------------------------------------------------------------------------


def test_schema_1_derivation_reproduces_today() -> None:
    derived = derive_scenario_variants(
        schema_version=1, role_chain=(OP, DDS), has_prefab_handoff=True
    )
    assert derived.supported.card_source == (CardSource.CALLER_VOICE, CardSource.GENERATED_CARD)
    assert derived.supported.dds_mode == (DdsMode.RESOURCE_PICKER,)
    assert derived.supported.dds_card_check == (DdsCardCheck.OFF, DdsCardCheck.ON)
    assert derived.supported.dds_brigade_call == (DdsBrigadeCall.OFF,)
    assert derived.default.card_source is CardSource.CALLER_VOICE
    assert derived.default.dds_mode is DdsMode.RESOURCE_PICKER


def test_schema_1_without_a_prefab_supports_only_the_caller() -> None:
    derived = derive_scenario_variants(
        schema_version=1, role_chain=(OP, DDS), has_prefab_handoff=False
    )
    assert derived.supported.card_source == (CardSource.CALLER_VOICE,)


def test_schema_1_dds_only_chain_defaults_to_the_generated_card() -> None:
    derived = derive_scenario_variants(schema_version=1, role_chain=(DDS,), has_prefab_handoff=True)
    assert derived.supported.card_source == (CardSource.GENERATED_CARD,)
    assert derived.default.card_source is CardSource.GENERATED_CARD


def test_schema_2_without_the_key_takes_the_product_default_where_supported() -> None:
    """The derived `dds_mode` support is `{RESOURCE_PICKER}` (no responders section), so the E5
    flip to `MEMO_STATUSES` cannot apply to a document without `variants` (§70.2.2)."""
    with_prefab = derive_scenario_variants(
        schema_version=2, role_chain=(OP, DDS), has_prefab_handoff=True
    )
    assert with_prefab.default == PRODUCT_DEFAULT_VARIANTS.model_copy(
        update={"dds_mode": DdsMode.RESOURCE_PICKER}
    )
    without_prefab = derive_scenario_variants(
        schema_version=2, role_chain=(OP, DDS), has_prefab_handoff=False
    )
    assert without_prefab.default.card_source is CardSource.CALLER_VOICE


def test_a_declared_key_wins() -> None:
    declared = derive_scenario_variants(
        schema_version=2, role_chain=(OP, DDS), has_prefab_handoff=False, declared=ALL_SUPPORTED
    )
    assert declared is ALL_SUPPORTED


def test_legacy_session_variants_read_off_the_stage_chain() -> None:
    assert legacy_session_variants((OP, DDS)).card_source is CardSource.CALLER_VOICE
    assert legacy_session_variants((DDS,)).card_source is CardSource.GENERATED_CARD


def test_the_view_filters_unimplemented_values_and_keeps_an_implemented_default() -> None:
    view = available_scenario_variants(ALL_SUPPORTED)
    assert view.supported.dds_mode == (DdsMode.RESOURCE_PICKER, DdsMode.MEMO_STATUSES)
    assert view.supported.dds_card_check == (DdsCardCheck.OFF,)
    assert view.supported.dds_brigade_call == (DdsBrigadeCall.OFF,)
    assert view.supported.card_source == ALL_SUPPORTED.supported.card_source
    assert view.default.dds_mode is DdsMode.MEMO_STATUSES
    check_default = ALL_SUPPORTED.model_copy(
        update={
            "default": PRODUCT_DEFAULT_VARIANTS.model_copy(
                update={"dds_card_check": DdsCardCheck.ON}
            )
        }
    )
    assert available_scenario_variants(check_default).default.dds_card_check is DdsCardCheck.OFF


# ---------------------------------------------------------------------------------------------
# Resolution (§70.2.2 home 2)
# ---------------------------------------------------------------------------------------------


def test_an_empty_request_takes_the_scenario_default() -> None:
    assert resolve_variants(PartialVariants(), ALL_SUPPORTED) == PRODUCT_DEFAULT_VARIANTS


def test_a_request_value_overrides_the_scenario_default() -> None:
    resolved = resolve_variants(PartialVariants(card_source=CardSource.CALLER_VOICE), ALL_SUPPORTED)
    assert resolved.card_source is CardSource.CALLER_VOICE
    assert resolved.dds_mode is DdsMode.MEMO_STATUSES
    picker = resolve_variants(PartialVariants(dds_mode=DdsMode.RESOURCE_PICKER), ALL_SUPPORTED)
    assert picker.dds_mode is DdsMode.RESOURCE_PICKER


def test_memo_statuses_is_available_from_e5a() -> None:
    """`MEMO_STATUSES` resolves wherever the scenario supports it (§70.11)."""
    resolved = resolve_variants(PartialVariants(dds_mode=DdsMode.MEMO_STATUSES), ALL_SUPPORTED)
    assert resolved.dds_mode is DdsMode.MEMO_STATUSES


@pytest.mark.parametrize(
    ("switch", "value"),
    [
        ("dds_card_check", DdsCardCheck.ON),
        ("dds_brigade_call", DdsBrigadeCall.ON),
    ],
)
def test_every_unimplemented_value_is_not_available(switch: str, value: Any) -> None:
    with pytest.raises(VariantNotAvailableError) as excinfo:
        resolve_variants(PartialVariants(**{switch: value}), ALL_SUPPORTED)
    assert excinfo.value.code == "VARIANT_NOT_AVAILABLE"
    assert (excinfo.value.switch, excinfo.value.value) == (switch, value.value)


def test_not_available_is_checked_before_not_supported() -> None:
    """Brigade `ON` is neither implemented nor supported by a schema-1 scenario: availability
    wins, so an unimplemented value never reaches content validation (§70.2.2)."""
    schema_1 = derive_scenario_variants(
        schema_version=1, role_chain=(OP, DDS), has_prefab_handoff=False
    )
    with pytest.raises(VariantNotAvailableError):
        resolve_variants(
            PartialVariants(
                card_source=CardSource.GENERATED_CARD, dds_brigade_call=DdsBrigadeCall.ON
            ),
            schema_1,
        )


def test_a_value_outside_supported_is_not_supported() -> None:
    schema_1 = derive_scenario_variants(
        schema_version=1, role_chain=(OP, DDS), has_prefab_handoff=False
    )
    with pytest.raises(VariantNotSupportedError) as excinfo:
        resolve_variants(PartialVariants(card_source=CardSource.GENERATED_CARD), schema_1)
    assert excinfo.value.code == "VARIANT_NOT_SUPPORTED"


def test_an_unimplemented_scenario_default_is_not_available() -> None:
    check_default = ALL_SUPPORTED.model_copy(
        update={
            "default": PRODUCT_DEFAULT_VARIANTS.model_copy(
                update={"dds_card_check": DdsCardCheck.ON}
            )
        }
    )
    with pytest.raises(VariantNotAvailableError):
        resolve_variants(PartialVariants(), check_default)


# ---------------------------------------------------------------------------------------------
# The effective chain (§70.2.4 "Flow") and the record (§70.2.2 home 3)
# ---------------------------------------------------------------------------------------------


def test_effective_role_chain() -> None:
    assert effective_role_chain((OP, DDS), CardSource.CALLER_VOICE) == (OP, DDS)
    assert effective_role_chain((OP, DDS), CardSource.GENERATED_CARD) == (DDS,)
    assert effective_role_chain((DDS,), CardSource.GENERATED_CARD) == (DDS,)
    assert effective_role_chain((OP,), CardSource.GENERATED_CARD) == ()


def _create(
    variants: SessionVariants | None, *, session_mode: SessionMode = SessionMode.SINGLE_ROLE
) -> tuple[SimulationSession, Any]:
    version = b.scenario_version(role_chain=(OP, DDS), with_prefab_handoff=True)
    scenario_id, slug = b.scenario_ids()
    count = 1 if variants is not None and variants.card_source is CardSource.GENERATED_CARD else 2
    return create_session(
        session_id=b.SESSION_ID,
        incident_id=b.INCIDENT_ID,
        stage_ids=b.stage_ids(count),
        scenario_version=version,
        scenario_id=scenario_id,
        scenario_slug=slug,
        session_mode=session_mode,
        created_by=b.INSTRUCTOR,
        participants=[(b.user("dds"), DDS)],
        variants=variants,
    )


def test_generated_card_runs_the_dds_suffix_and_records_both_chains() -> None:
    generated = PRODUCT_DEFAULT_VARIANTS
    session, events = _create(generated)
    assert [stage.role_type for stage in session.stages] == [DDS]
    assert session.variants == generated
    payload = events[0].payload
    validate_payload(EventType.SESSION_CREATED, payload)
    assert payload["role_chain"] == ["DDS"]
    assert payload["scenario_role_chain"] == ["OPERATOR_112", "DDS"]
    assert payload["variants"] == {
        "card_source": "GENERATED_CARD",
        "dds_mode": "MEMO_STATUSES",
        "dds_card_check": "OFF",
        "dds_brigade_call": "OFF",
    }


def test_single_role_counts_the_effective_chain() -> None:
    """`EXACTLY_ONE` on the effective chain: the two-stage demo shape runs `SINGLE_ROLE` as DDS."""
    session, _events = _create(PRODUCT_DEFAULT_VARIANTS, session_mode=SessionMode.SINGLE_ROLE)
    assert session.stages[0].participant_user_id == b.user("dds")


def test_no_variants_takes_the_scenario_default_caller_voice() -> None:
    session, events = _create(None, session_mode=SessionMode.MULTI_TRAINEE)
    assert [stage.role_type for stage in session.stages] == [OP, DDS]
    assert session.variants.card_source is CardSource.CALLER_VOICE
    assert events[0].payload["role_chain"] == events[0].payload["scenario_role_chain"]


def test_a_session_without_recorded_variants_reads_the_legacy_derivation() -> None:
    session, _events = _create(None, session_mode=SessionMode.MULTI_TRAINEE)
    data = session.model_dump()
    data.pop("variants")
    assert SimulationSession.model_validate(data).variants == legacy_session_variants((OP, DDS))
