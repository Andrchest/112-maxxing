"""The routing resolver on the real pack `v046_24-r1` (I3 E2b′; HLD 70 §70.6.4, D18, A-1).

Fixtures (the fixture pack is retired, B1 §3):

* the organizer's own worked examples — «КАРТОЧКА 112.docx» images 19, 22, 24 and 39, each a card
  selection with the services bar the real system pulled (B1 §2). Images 19/22/24 must match
  exactly; image 39 reproduces seven of its eight services — «Деп. ЖКХ» has no cell in row
  1020101, a finding recorded in the E2b′ report, not bent into the resolver;
* the DDS memo's worked examples (`requirements/normalized/SRC-005-tickets-and-dds-memo.md`):
  each asserts the services the memo says were involved. The 14/16 groups have no questionnaire
  on the v2 card, so those cards carry the «Класс.:» pick (`incident.classifier_code`);
* the manager's step-1 fallback on a 104 and a «Взрыв» selection (their questionnaires stop at
  the first question level).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from app.domain.routing.resolve import (
    EMPTY_RESOLUTION,
    PackRouting,
    ReasonSource,
    RowMatch,
    notification_list,
    pack_routing,
    resolve_notification_list,
)
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

REFERENCE = FileReferenceCatalog().catalog()
_ROUTING = pack_routing(REFERENCE, "v046_24-r1")
assert _ROUTING is not None
ROUTING: PackRouting = _ROUTING

SHCHUKINO = {"address.okrug": "СЗАО", "address.district": "Щукино"}

# «КАРТОЧКА 112.docx» — 101 · Улица · Открытое пламя/Дым · Нет доступа · Мусор (address: Москва).
IMAGE_19: dict[str, Any] = {
    "incident.types": ["1"],
    "q.fire.where": ["на улице"],
    "q.fire.sign_street": ["открытое пламя / дым"],
    "q.fire.access": ["no_access"],
    "q.fire.street_object": ["мусор"],
}
IMAGE_22 = {**IMAGE_19, "q.fire.place": ["tunnel"], "q.fire.threat_to_people": ["threat_to_people"]}
IMAGE_24 = {**IMAGE_22, "q.fire.offence": ["offence"]}
IMAGE_39: dict[str, Any] = {
    "incident.types": ["1"],
    "q.fire.where": ["транспорт"],
    "q.fire.sign_transport": ["открытое пламя / дым"],
    "q.fire.access": ["no_access"],
    "q.fire.transport_object": ["общественный транспорт"],
    "q.fire.threat_to_people": ["threat_to_people"],
    "q.fire.medical_help": ["medical_help"],
    "q.fire.evacuation": ["evacuation_required"],
}


def resolve(values: Mapping[str, Any]):  # type: ignore[no-untyped-def]
    return ROUTING.resolve(values)


# -- the organizer's screenshots ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("frame", "values", "bar"),
    [
        ("image19", IMAGE_19, {"FIRE_RESCUE", "TSODD", "OATI"}),
        ("image22", IMAGE_22, {"FIRE_RESCUE", "TSEMP", "TSODD", "OATI"}),
        ("image24", IMAGE_24, {"FIRE_RESCUE", "POLICE", "TSEMP", "TSODD", "OATI"}),
    ],
)
def test_the_screenshot_bars_are_reproduced_exactly(
    frame: str, values: Mapping[str, Any], bar: set[str]
) -> None:
    resolution = resolve(values)
    assert set(resolution.auto_services) == bar, frame
    # «Открытое пламя / Дым» is one chip for two признаки: the union of both rows until «Класс.:»
    assert resolution.classifier_code is None
    assert resolution.candidate_codes == ("1010101", "1010102")
    assert resolution.main_service == "FIRE_RESCUE"


def test_image39_reproduces_seven_of_eight_and_deps_zhkh_is_a_finding() -> None:
    resolution = resolve(IMAGE_39)
    seven = {"FIRE_RESCUE", "POLICE", "TSEMP", "TSODD", "MOSGORTRANS", "MOSBEZ", "OATI"}
    assert set(resolution.auto_services) == seven
    # Finding (E2b′ report): the real bar also shows «Деп. ЖКХ»; row 1020101 has no DEP_ZHKH cell.
    assert "DEP_ZHKH" not in resolution.auto_services
    assert resolution.candidate_codes[0] == "1020101"


def test_any_holding_sub_column_notifies_image22() -> None:
    """G5: with УЛ and НД both set, ОДС ПСЦ's column Q (УЛ) is empty and S (НД) is filled — the
    bar still shows Служба 101, so any holding sub-column counts; the reason names S."""
    reason = next(r for r in resolve(IMAGE_22).reasons if r.service_id == "FIRE_RESCUE")
    assert reason.column in {"MCHS_SLUZHBA_101", "MCHS_ODS_PSC"}
    assert (reason.column, reason.sub_column) == ("MCHS_ODS_PSC", "S")
    assert reason.source is ReasonSource.CLASSIFIER
    assert reason.row_match is RowMatch.COVERED


def test_display_false_orgs_are_informed_never_auto() -> None:
    resolution = resolve(IMAGE_19)
    hidden = {entry.id for entry in ROUTING.catalog.services if not entry.display}
    assert set(resolution.informed_services) <= hidden
    assert {"APPARAT_MERA", "FSO", "GKU_NTU", "GOR_KHOZYAYSTVO"} <= set(
        resolution.informed_services
    )
    assert not set(resolution.auto_services) & hidden
    assert not set(notification_list(resolution.auto_services, ())) & hidden


def test_classifier_code_selects_that_row_alone() -> None:
    both = resolve({**IMAGE_22, **SHCHUKINO})
    only_smoke = resolve({**IMAGE_22, **SHCHUKINO, "incident.classifier_code": "1010102"})
    assert only_smoke.classifier_code == "1010102"
    assert only_smoke.candidate_codes == ("1010102",)
    assert {r.row_match for r in only_smoke.reasons} == {RowMatch.CLASSIFIER_CODE}
    assert set(only_smoke.auto_services) <= set(both.auto_services)
    # the дым row lacks ЦОДД and ОАТИ (B1 §2 finding 5): the union was wider
    assert "TSODD" in both.auto_services and "TSODD" not in only_smoke.auto_services


def test_an_unknown_classifier_code_is_ignored() -> None:
    assert resolve({**IMAGE_19, "incident.classifier_code": "0000000"}) == resolve(IMAGE_19)


# -- step 3: the district and the prefecture ДДС --------------------------------------------------


def test_territorial_column_adds_the_district_and_prefecture_dds() -> None:
    resolution = resolve({**IMAGE_19, **SHCHUKINO})
    assert {"DDS_DISTRICT_SHCHUKINO", "DDS_PREFECTURE_SZAO"} <= set(resolution.auto_services)
    territorial = [r for r in resolution.reasons if r.source is ReasonSource.TERRITORIAL]
    assert {r.column for r in territorial} == {"TERRITORIAL_OIV"}
    assert {r.sub_column for r in territorial} == {"BW"}


def test_without_address_there_is_no_territorial_leg() -> None:
    assert not any(service.startswith("DDS_") for service in resolve(IMAGE_19).auto_services)
    district_only = resolve({**IMAGE_19, "address.district": "Щукино"})
    assert "DDS_DISTRICT_SHCHUKINO" in district_only.auto_services
    assert not any(s.startswith("DDS_PREFECTURE_") for s in district_only.auto_services)


def test_tinao_reads_column_bx() -> None:
    resolution = resolve(
        {
            "incident.types": ["14"],
            "incident.classifier_code": "14020300",
            "address.okrug": "ТиНАО",
            "address.district": "Щукино",
        }
    )
    territorial = [r for r in resolution.reasons if r.source is ReasonSource.TERRITORIAL]
    assert {r.column for r in territorial} == {"TERRITORIAL_OIV_TINAO"}
    assert {r.sub_column for r in territorial} == {"BX"}
    assert "DDS_PREFECTURE_TINAO" in resolution.auto_services


# -- A-3 and empty cards ------------------------------------------------------------------------


def test_administrative_entries_produce_nothing() -> None:
    assert resolve({"incident.types": ["CONSULTATION", "TEST_CALL"], **SHCHUKINO}) == (
        EMPTY_RESOLUTION
    )


def test_a_group_the_card_says_nothing_about_yields_no_candidate() -> None:
    assert resolve({"incident.types": ["2"], **SHCHUKINO}) == EMPTY_RESOLUTION
    assert resolve({}) == EMPTY_RESOLUTION


# -- the step-1 group fallback (manager decision on E2b′) ---------------------------------------


def test_group_fallback_on_a_104_selection() -> None:
    resolution = resolve({"incident.types": ["13"], "q.gas.signs": ["Запах газа в помещении"]})
    assert resolution.candidate_codes, "the fallback finds the rows under the chip"
    assert all(code.startswith("1302") for code in resolution.candidate_codes)
    assert {r.row_match for r in resolution.reasons} == {RowMatch.GROUP_FALLBACK}
    assert "GAS_SERVICE" in resolution.auto_services
    assert resolution.classifier_code is None


def test_group_fallback_on_an_explosion_selection() -> None:
    resolution = resolve({"incident.types": ["3"], "q.explosion.where": ["Взрыв объект"]})
    assert all(code.startswith("301") for code in resolution.candidate_codes)
    assert len(resolution.candidate_codes) > 1
    assert {r.row_match for r in resolution.reasons} == {RowMatch.GROUP_FALLBACK}
    assert {"FIRE_RESCUE", "POLICE", "AMBULANCE"} <= set(resolution.auto_services)


def test_covered_rows_do_not_use_the_fallback() -> None:
    assert RowMatch.GROUP_FALLBACK not in {r.row_match for r in resolve(IMAGE_24).reasons}


def test_the_fallback_is_per_group() -> None:
    """101 fully covered + «Взрыв» at the first level: each group answers for itself."""
    resolution = resolve(
        {**IMAGE_19, "incident.types": ["1", "3"], "q.explosion.where": ["Взрыв транспорт"]}
    )
    matches = {r.row_code[:1]: r.row_match for r in resolution.reasons}
    assert {"1010101", "1010102"} <= set(resolution.candidate_codes)
    assert any(code.startswith("302") for code in resolution.candidate_codes)
    assert RowMatch.COVERED in matches.values()


# -- the DDS memo's worked examples (A-1) -------------------------------------------------------


@pytest.mark.parametrize(
    ("req", "values", "memo_services"),
    [
        # REQ-5314: «Повреждение дорожного покрытия» — ДДС района.
        (
            "REQ-5314",
            {"incident.types": ["16"], "incident.classifier_code": "16100000", **SHCHUKINO},
            {"DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5315: «Застревание в лифте в жилом доме» — ДДС района.
        (
            "REQ-5315",
            {"incident.types": ["14"], "incident.classifier_code": "14100100", **SHCHUKINO},
            {"DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5323 (a): «Застревание в лифте» — «Мослифт» и ДДС района.
        (
            "REQ-5323a",
            {"incident.types": ["14"], "incident.classifier_code": "14100100", **SHCHUKINO},
            {"MOSLIFT", "DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5324: «Прорыв трубы с горячей водой в жилом доме, заливает подъезд» — ДДС района.
        (
            "REQ-5324",
            {"incident.types": ["14"], "incident.classifier_code": "14020300", **SHCHUKINO},
            {"DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5316 / REQ-5322 (a): «Сработала пожарная сигнализация в жилом доме» — ДДС района;
        # reachable through the v2 card's own chips (101 · Дом · Сработала сигнализация).
        (
            "REQ-5322a",
            {
                "incident.types": ["1"],
                "q.fire.where": ["жилой дом"],
                "q.fire.sign_house": ["сигнализация"],
                **SHCHUKINO,
            },
            {"DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5322 (b): «Оборван провод во дворе жилого дома» — ДДС района (14110301).
        (
            "REQ-5322b",
            {"incident.types": ["14"], "incident.classifier_code": "14110301", **SHCHUKINO},
            {"DDS_DISTRICT_SHCHUKINO"},
        ),
        # REQ-5322 (c): «Задымление в подъезде жилого дома» — ДДС района, and Служба 101 made
        # the duplicate card; reachable through the chips (Дом · Открытое пламя/Дым · Подъезд).
        (
            "REQ-5322c",
            {
                "incident.types": ["1"],
                "q.fire.where": ["жилой дом"],
                "q.fire.sign_house": ["открытое пламя / дым"],
                "q.fire.house_objects": ["подъезд"],
                **SHCHUKINO,
            },
            {"DDS_DISTRICT_SHCHUKINO", "FIRE_RESCUE"},
        ),
    ],
)
def test_memo_worked_example(req: str, values: Mapping[str, Any], memo_services: set[str]) -> None:
    resolution = resolve(values)
    assert memo_services <= set(resolution.auto_services), (req, resolution.auto_services)


def test_the_resolver_is_pure_and_deterministic() -> None:
    values = {**IMAGE_24, **SHCHUKINO}
    snapshot = {
        key: list(value) if isinstance(value, list) else value for key, value in values.items()
    }
    first = resolve_notification_list(
        ROUTING.classifier, ROUTING.catalog, values, schema=ROUTING.schema
    )
    assert first == resolve(values)
    assert values == snapshot


def test_a_pack_without_a_classifier_has_no_routing() -> None:
    assert pack_routing(REFERENCE, "legacy-r1") is None
    assert pack_routing(REFERENCE, "no-such-pack") is None


def test_notification_list_is_auto_then_new_manual() -> None:
    assert notification_list(("A", "B"), ("B", "C")) == ("A", "B", "C")  # type: ignore[arg-type]
