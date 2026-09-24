"""The organizer's 96 ticket calls as schema-2 scenarios (I3 E8; HLD 30 §30.13).

`scenarios/tickets/ticket-NN-call-M/v1.yaml` is one scenario per call of «Билеты- задачи по C 112»
(32 tickets × 3 calls, REQ-5203/REQ-5206), each marked `provenance.generation_candidate: true`;
`…-decline` and `…-card-error` directories are special variants next to their base. This module
proves, without a database, that every file loads and validates on pack `v046_24-r1`, that the
variants are what E8 promises, and that every base scenario's prefab card resolves through the
routing resolver (HLD 70 §70.6.4) to a non-empty automatic notification list — or is listed in
`ROUTING_ALLOWLIST` with the reason the classifier yields nothing for it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.domain.dds.response import ServiceResponseStatus
from app.domain.events.types import EventType
from app.domain.routing.resolve import notification_list, pack_routing
from app.domain.scenario.sections import CALLS_PER_TICKET, TICKET_COUNT, ProvenanceSource
from app.domain.scenario.version import ScenarioVersion
from app.domain.session.variants import CardSource, DdsBrigadeCall, DdsCardCheck, DdsMode
from app.infrastructure.reference.file_catalog import FileReferenceCatalog
from app.infrastructure.scenarios.yaml_loader import discover, load_scenario_version, scenario_slug

TICKETS_DIR = Path(__file__).resolve().parents[5] / "scenarios" / "tickets"
PACK = "v046_24-r1"
BASE_SLUG = re.compile(r"^ticket-(?P<ticket>\d{2})-call-(?P<call>\d)$")
VARIANT_SLUG = re.compile(r"^(?P<base>ticket-\d{2}-call-\d)-(?P<kind>decline|card-error)$")

ROUTING_ALLOWLIST: dict[str, str] = {
    "ticket-18-call-1": (
        "«Видит пожар, что горит не знает»: the card answers «Что горит неизвестно», which the "
        "card schema binds to no признак (routing: none) and v046_24 has no street-fire row for "
        "an unknown object, so no row is a candidate; the prefab adds Служба 101 by hand."
    ),
    "ticket-32-call-3": (
        "Row 14030203 «Горит уличное освещение в дневное время» counts only «Территориальные "
        "ОИВ»; the address (МКАД 68–74 км, both sides) names no single district or okrug, so "
        "no territorial ДДС resolves; the prefab adds ОЭК (the row's main service) by hand."
    ),
}
"""Base scenarios whose prefab card legitimately resolves to no automatic service, with why."""

REFERENCE = FileReferenceCatalog().catalog()
ROUTING = pack_routing(REFERENCE, PACK)


def _versions() -> dict[str, ScenarioVersion]:
    return {scenario_slug(path): load_scenario_version(path) for path in discover(TICKETS_DIR)}


VERSIONS = _versions()
BASES = {slug: version for slug, version in VERSIONS.items() if BASE_SLUG.match(slug)}
VARIANTS = {slug: version for slug, version in VERSIONS.items() if VARIANT_SLUG.match(slug)}


def test_every_file_is_a_base_or_a_variant() -> None:
    assert set(VERSIONS) == set(BASES) | set(VARIANTS)


def test_one_base_scenario_per_ticket_call() -> None:
    expected = {
        f"ticket-{ticket:02d}-call-{call}"
        for ticket in range(1, TICKET_COUNT + 1)
        for call in range(1, CALLS_PER_TICKET + 1)
    }
    assert set(BASES) == expected
    assert len(BASES) == 96


@pytest.mark.parametrize("slug", sorted(VERSIONS))
def test_provenance_names_the_ticket_call_and_marks_a_generation_candidate(slug: str) -> None:
    version = VERSIONS[slug]
    match = BASE_SLUG.match(slug) or BASE_SLUG.match(VARIANT_SLUG.match(slug)["base"])  # type: ignore[index]
    assert match is not None
    assert version.provenance is not None
    assert version.provenance.source is ProvenanceSource.TICKET
    assert (version.provenance.ticket, version.provenance.call) == (
        int(match["ticket"]),
        int(match["call"]),
    )
    assert version.provenance.generation_candidate is True


@pytest.mark.parametrize("slug", sorted(VERSIONS))
def test_schema_2_on_the_v046_pack_with_the_e8_variants(slug: str) -> None:
    version = VERSIONS[slug]
    assert version.schema_version == 2
    assert version.reference_pack == PACK
    assert version.variants is not None
    supported, default = version.variants.supported, version.variants.default
    assert set(supported.card_source) == {CardSource.GENERATED_CARD, CardSource.CALLER_VOICE}
    assert default.card_source is CardSource.GENERATED_CARD
    assert supported.dds_mode == (DdsMode.MEMO_STATUSES,)
    assert default.dds_mode is DdsMode.MEMO_STATUSES
    assert set(supported.dds_card_check) == {DdsCardCheck.OFF, DdsCardCheck.ON}
    expected_check = DdsCardCheck.ON if slug.endswith("-card-error") else DdsCardCheck.OFF
    assert default.dds_card_check is expected_check
    # D28 (owner 2026-09-25): the ДДС phone is ON by default and may be switched OFF.
    assert set(supported.dds_brigade_call) == {DdsBrigadeCall.OFF, DdsBrigadeCall.ON}
    assert default.dds_brigade_call is DdsBrigadeCall.ON
    assert version.expected_response.prefab_handoff is not None


@pytest.mark.parametrize("slug", sorted(BASES))
def test_the_prefab_card_resolves_to_a_non_empty_notification_list(slug: str) -> None:
    prefab = BASES[slug].expected_response.prefab_handoff
    assert prefab is not None
    resolution = ROUTING.resolve(prefab.card_values)
    if slug in ROUTING_ALLOWLIST:
        assert resolution.auto_services == (), f"{slug} resolves now; drop it from the allowlist"
    else:
        assert resolution.auto_services, f"{slug}: the resolver notifies nobody"
    assert notification_list(resolution.auto_services, prefab.recipient_services)


def test_the_routing_allowlist_names_only_base_scenarios() -> None:
    assert set(ROUTING_ALLOWLIST) <= set(BASES)


def test_at_least_six_competence_declines_scripted_through_responders() -> None:
    declines = {slug: v for slug, v in VARIANTS.items() if slug.endswith("-decline")}
    assert len(declines) >= 6
    for slug, version in declines.items():
        responders = version.expected_response.responders
        assert isinstance(responders, dict), slug
        prefab = version.expected_response.prefab_handoff
        assert prefab is not None
        legs = notification_list(
            ROUTING.resolve(prefab.card_values).auto_services, prefab.recipient_services
        )
        declined = [
            service
            for service, steps in responders.items()
            if any(step.status is ServiceResponseStatus.NOT_ACCEPTED for step in steps)
        ]
        assert len(declined) == 1, slug
        (service,) = declined
        assert service in legs, f"{slug}: {service} is not a leg of the card"
        final = responders[service][-1]
        assert final.status is ServiceResponseStatus.NOT_ACCEPTED
        assert final.comment_ru and final.comment_ru.strip(), slug
        rule = next(r for r in version.scoring_rules if r.rule_id == "memo_competence_decline")
        assert rule.config["payload_match"]["service_type"] == service


def test_at_least_six_card_errors_with_card_check_on_and_a_flag_rule() -> None:
    errors = {slug: v for slug, v in VARIANTS.items() if slug.endswith("-card-error")}
    assert len(errors) >= 6
    for slug, version in errors.items():
        base = BASES[VARIANT_SLUG.match(slug)["base"]]  # type: ignore[index]
        rule = next(r for r in version.scoring_rules if r.rule_id == "dds_card_issue_flagged")
        assert rule.config["event_type"] == EventType.DDS_CARD_ISSUE_FLAGGED.value
        assert dict(rule.applies_to_variants) == {"dds_card_check": ("ON",)}
        field_path = rule.config["payload_match"]["field_path"]
        wrong = version.expected_response.prefab_handoff
        right = base.expected_response.prefab_handoff
        assert wrong is not None and right is not None
        assert wrong.card_values.get(field_path) != right.card_values.get(field_path), slug


def test_the_index_lists_every_base_scenario() -> None:
    index = (TICKETS_DIR / "README.md").read_text(encoding="utf-8")
    for slug in BASES:
        assert f"`{slug}`" in index, slug
