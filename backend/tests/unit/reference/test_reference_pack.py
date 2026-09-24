"""The reference pack's content (I3 E2a; HLD 70 §70.6.1-§70.6.3, D18, A-1, A-6, A-13).

* the «СЛУЖБЫ 112» transcription covers every picker frame of the docx and every entry the REQ
  digests sample (REQ-3042, REQ-3043);
* `services/v1.yaml` starts with the six legacy ids, which keep the Russian labels the product
  shows today, and every entry is a well-formed, unique catalog id;
* the classifier's row and column counts are the ones REQ-5701-REQ-5717 state, read out of
  `requirements/normalized/SRC-005-classifier-v046-24.md` at test time (never retyped here);
* regenerate-and-diff: the tools rebuild every generated file byte for byte — the classifier half
  needs `openpyxl` (the `tools` dependency group) and is skipped without it;
* the import boundary: `backend/app` never imports the readers (A-13);
* the file-backed `ReferencePort` resolves the six legacy ids.
"""

from __future__ import annotations

import ast
import json
import re
import zipfile
from pathlib import Path

import pytest
import yaml
from app.domain.enums import LEGACY_SERVICE_IDS
from app.infrastructure.reference.file_catalog import FileReferenceCatalog, load_reference
from tools import import_card_schema, import_manifest, import_services

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_DIR = REPO_ROOT / "reference"
SERVICES_DOC = REPO_ROOT / import_manifest.SERVICES_SOURCE
DOMAIN_DOCS = REPO_ROOT / "requirements" / "normalized" / "SRC-001-domain-docs.md"
CLASSIFIER_DOCS = REPO_ROOT / "requirements" / "normalized" / "SRC-005-classifier-v046-24.md"
RU_TS = REPO_ROOT / "frontend" / "src" / "shared" / "i18n" / "ru.ts"

TRANSCRIPTION = import_services.read_transcription()
SERVICES = yaml.safe_load((REFERENCE_DIR / "services" / "v1.yaml").read_text(encoding="utf-8"))
ROWS = json.loads((REFERENCE_DIR / "classifier" / "v046_24.json").read_text(encoding="utf-8"))
COLUMNS = json.loads(
    (REFERENCE_DIR / "classifier" / "v046_24.columns.json").read_text(encoding="utf-8")
)

# -- the «СЛУЖБЫ 112» transcription ---------------------------------------------------------------

#: REQ-3042's sampled city-level entries, as the digest writes them. Two are the digest's own
#: shorthand, resolved against the screenshots: «ГБУ АД ВАО / СВАО / … (ГБУ Автодороги, per-okrug)»
#: is six entries, and «112 Моск. обл.» is spelled «112 Мос. обл.» on the picker (frame 4).
REQ_3042_SAMPLES: tuple[str, ...] = (
    'Служба 101 (ГУ МЧС России по г.Москве, ГКУ "Пожарно спасательный центр" ОДС)',
    "ФСБ",
    "ЦЭМП",
    "Служба 103 (ГБУ города Москвы Станция скорой и неотложной медицинской помощи им.А.С. Пучкова)",
    'Служба 104 (АО "МОСГАЗ" Диспетчерское управление)',
    "ОГДЦ",
    'ЦОДД (ГКУ "Центр организации дорожного движения")',
    "Гормост (Гормост)",
    "Мосгортранс",
    "Автодороги",
    'Мосводоканал (АО "Мосводоканал")',
    "Россети МР",
    "МОЭК",
    "Деп. ЖКХ (Департамент ЖКХ)",
    "Метро",
    "АСУ НС (Автоматизированная система управления...",
    "Мос.Без. (Московская Безопасность)",
    "112 Моск. обл. (112 Московской области)",
    "ФГУП РСВО (Российские сети вещания и оповещения)",
    "ОЭК (Объединенная энергетическая компания)",
    "Мослифт (Лифт МСК)",
    "Мосводосток (Мосводосток)",
    "Москоллектор (Москоллектор)",
    "Воен. комендатура (Воен. комендатура)",
    "ОАТИ (Объединение Административно-Технических Инспекций города Москвы)",
    "ГБУ МСППН (Московская служба психологической помощи населению ГБУ города Москвы)",
    "Мособлгаз (Мособлгаз)",
    "Центррегионводхоз (Центррегионводхоз)",
    "ГБУ АД ВАО",
    "ГБУ АД СВАО",
    "ГБУ АД ЮВАО",
    "ГБУ АД ЗелАО",
    "ГБУ АД ЮЗАО",
    "ГБУ АД ЮАО",
    "Департамент культуры города Москвы",
    "ГКУ ЦСА (Центр социальной помощи)",
    "Мостуризм (Комитет по туризму города Москвы)",
    "Департамент строительства",
    "Комитет ветеринарии города Москвы",
    "Мосжилинспекция (Государственная жилищная инспекция города Москвы)",
)
REQ_SPELLING_ON_SCREEN = {"112 Моск. обл.": "112 Мос. обл."}


def _norm(text: str) -> str:
    """Collapse whitespace, and the stray space the picker puts before a comma or parenthesis."""
    return re.sub(r"\s+([,)])", r"\1", re.sub(r"\s+", " ", text)).strip()


def _transcribed_forms() -> set[str]:
    forms: set[str] = set()
    for entry in TRANSCRIPTION:
        forms.add(_norm(entry.short_name_ru))
        if entry.full_name_ru:
            forms.add(_norm(entry.full_name_ru))
            forms.add(_norm(f"{entry.short_name_ru} ({entry.full_name_ru})"))
    return forms


def _is_transcribed(sample: str, forms: set[str]) -> bool:
    for req, screen in REQ_SPELLING_ON_SCREEN.items():
        sample = sample.replace(req, screen)
    wanted = _norm(sample)
    if wanted.endswith("..."):
        return any(form.startswith(wanted[:-3]) for form in forms)
    return wanted in forms


def test_the_transcription_covers_every_picker_frame_of_the_docx() -> None:
    with zipfile.ZipFile(SERVICES_DOC) as docx:
        images = [name for name in docx.namelist() if re.match(r"word/media/image\d+\.png$", name)]
    frames = {entry.frame for entry in TRANSCRIPTION}
    assert len(images) == 55  # A-6: «all 55 picker frames»
    assert frames == set(range(1, len(images) + 1))


def test_the_transcription_keeps_every_entry_once() -> None:
    entries = [(entry.short_name_ru, entry.full_name_ru) for entry in TRANSCRIPTION]
    assert len(entries) == len(set(entries))
    assert [entry.frame for entry in TRANSCRIPTION] == sorted(
        entry.frame for entry in TRANSCRIPTION
    )


def test_every_req_3042_sampled_city_entry_is_transcribed() -> None:
    forms = _transcribed_forms()
    missing = [sample for sample in REQ_3042_SAMPLES if not _is_transcribed(sample, forms)]
    assert not missing


def test_every_req_3043_sampled_district_entry_is_transcribed() -> None:
    text = DOMAIN_DOCS.read_text(encoding="utf-8")
    section = text[text.index("### REQ-3043") : text.index("### REQ-3044")]
    verbatim = section[section.index("**Verbatim") : section.index("**English:**")]
    samples = re.findall(r'"(Поселение [^"]+|Упр\. района [^"]+)"', verbatim.replace("\n", " "))
    assert len(samples) >= 25, "REQ-3043's sample list could not be read"
    forms = _transcribed_forms()
    assert [sample for sample in samples if not _is_transcribed(sample, forms)] == []


# -- services/v1.yaml ------------------------------------------------------------------------------


def _ru_labels() -> dict[str, str]:
    return dict(re.findall(r"^\s+(serviceType\w+): '([^']*)',$", RU_TS.read_text(), re.M))


def test_the_catalog_starts_with_the_six_legacy_ids_and_their_todays_labels() -> None:
    services = SERVICES["services"]
    assert tuple(entry["id"] for entry in services[:6]) == LEGACY_SERVICE_IDS
    labels = _ru_labels()
    keys = {
        "FIRE_RESCUE": "serviceTypeFireRescue",
        "POLICE": "serviceTypePolice",
        "AMBULANCE": "serviceTypeAmbulance",
        "GAS_SERVICE": "serviceTypeGasService",
        "UTILITY_EMERGENCY": "serviceTypeUtilityEmergency",
        "EDDS": "serviceTypeEdds",
    }
    for entry in services[:6]:
        assert entry["name_ru"] == labels[keys[entry["id"]]], entry["id"]
    by_id = {entry["id"]: entry for entry in services}
    assert [by_id[i]["code"] for i in ("FIRE_RESCUE", "POLICE", "AMBULANCE", "GAS_SERVICE")] == [
        "101",
        "102",
        "103",
        "104",
    ]
    assert by_id["AMBULANCE"]["status_policy"] == "NO_REFUSAL"
    assert by_id["UTILITY_EMERGENCY"]["deprecated"] is True


def test_every_catalog_entry_is_well_formed() -> None:
    services = SERVICES["services"]
    ids = [entry["id"] for entry in services]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", service_id) for service_id in ids)
    orgs = set(COLUMNS["orgs"])
    for entry in services:
        assert entry["kind"] in {"CITY", "DISTRICT", "PREFECTURE", "DEPARTMENT"}
        assert entry["classifier_org_id"] is None or entry["classifier_org_id"] in orgs
        assert set(entry["classifier_org_ids"]) <= orgs
        assert entry["classifier_org_ids"][:1] == (
            [entry["classifier_org_id"]] if entry["classifier_org_id"] else []
        )
        if entry["kind"] == "DISTRICT":
            assert entry["district"] and entry["id"].startswith("DDS_DISTRICT_")
        if entry["kind"] == "PREFECTURE":
            assert entry["okrug"] and entry["id"].startswith("DDS_PREFECTURE_")
    # 6 legacy + every transcribed entry except the four «Служба 10N» the legacy ids absorb
    # (the displayed catalog, counted against the transcription) + one hidden entry per
    # classifier-only column group (I3 E3a, B1 G4, counted against the column map below).
    displayed = [entry for entry in services if entry["display"]]
    assert len(displayed) == 6 + len(TRANSCRIPTION) - 4


def test_every_classifier_only_org_is_a_hidden_catalog_entry() -> None:
    """B1 G4 / REQ-5280: an org whose routing cell can notify but that the picker never shows is
    a `display: false` entry, generated from `v046_24.columns.json` — none is silently dropped.
    «Территориальные ОИВ» are the resolver's district/prefecture step, never entries, and
    «ОДС ПСЦ» is `FIRE_RESCUE` (B1 finding 4)."""
    services = SERVICES["services"]
    answered = {org_id for entry in services for org_id in entry["classifier_org_ids"]}
    territorial = {"TERRITORIAL_OIV", "TERRITORIAL_OIV_TINAO"}
    assert set(COLUMNS["orgs"]) - territorial == answered
    hidden = [entry for entry in services if not entry["display"]]
    # 60 column groups − 2 territorial − the 40 the displayed catalog answers for
    # (39 `classifier_org_id`s + `MCHS_ODS_PSC` through FIRE_RESCUE).
    assert len(hidden) == 18
    for entry in hidden:
        assert entry["id"] == entry["classifier_org_id"]
        assert entry["classifier_org_ids"] == [entry["id"]]
        assert entry["name_ru"] == COLUMNS["orgs"][entry["id"]]["name_ru"]
        assert entry["kind"] in {"CITY", "DEPARTMENT"}


def test_fire_rescue_answers_for_both_mchs_columns() -> None:
    """B1 finding 4: the picker's «Служба 101 (…, ГКУ "Пожарно спасательный центр" ОДС)» is both
    the «Служба 101» and the «ОДС ПСЦ» column group of the classifier."""
    by_id = {entry["id"]: entry for entry in SERVICES["services"]}
    fire = by_id["FIRE_RESCUE"]
    assert fire["classifier_org_id"] == "MCHS_SLUZHBA_101"
    assert fire["classifier_org_ids"] == ["MCHS_SLUZHBA_101", "MCHS_ODS_PSC"]
    assert "MCHS_ODS_PSC" not in by_id


# -- the classifier against REQ-5701-REQ-5717 ------------------------------------------------------


def _req(number: int) -> str:
    text = CLASSIFIER_DOCS.read_text(encoding="utf-8")
    start = text.index(f"### REQ-{number} ")
    end = text.index("### REQ-", start + 1)
    return text[start:end]


def test_the_sheet_dimensions_are_req_5701s() -> None:
    req = _req(5701)
    dimensions = re.search(r"`ws\.dimensions` = `([A-Z0-9:]+)`", req)
    max_row = re.search(r"`max_row` = (\d+)", req)
    max_column = re.search(r"`max_column` = (\d+)", req)
    assert dimensions and max_row and max_column
    source = COLUMNS["source"]
    assert source["dimensions"] == dimensions.group(1)
    assert source["max_row"] == int(max_row.group(1))
    assert source["max_column"] == int(max_column.group(1))
    # A-L records + M «Главная служба» + one column per routing sub-column (REQ-5702-5705).
    sub_columns = sum(len(org["sub_columns"]) for org in COLUMNS["orgs"].values())
    assert 13 + sub_columns == int(max_column.group(1))


def test_the_row_and_category_counts_are_req_5707s_and_5708s() -> None:
    req = _req(5707)
    total = re.search(r"NEW: (\d+) total data rows \((\d+) category-header rows", req)
    assert total
    assert len(ROWS["rows"]) == int(total.group(1))
    assert len(ROWS["groups"]) == int(total.group(2))

    table = re.findall(r"^\| ([^|*]+?) \| (\d+) \| (\d+) \| [^|]+ \|$", _req(5708), re.M)
    assert len(table) == len(ROWS["groups"])
    counts: dict[int, int] = {}
    for row in ROWS["rows"]:
        counts[row["group_no"]] = counts.get(row["group_no"], 0) + 1
    for group, (name, _old, new) in zip(ROWS["groups"], table, strict=True):
        assert group["group_ru"] == name.strip()
        assert counts[group["group_no"]] == int(new), name


def test_req_5709s_two_new_rows_are_there() -> None:
    by_code = {row["code"]: row for row in ROWS["rows"]}
    for code in re.findall(r"Номер=(\d+)", _req(5709)):
        assert code in by_code
    assert by_code["24120200"]["final_type_ru"] == "БВС Регион"
    assert by_code["24120200"]["main_service"] == "МСР"


def test_every_routing_list_is_aligned_with_its_column_group() -> None:
    orgs = COLUMNS["orgs"]
    for row in ROWS["rows"]:
        for org_id, cells in row["routing"].items():
            sub_columns = orgs[org_id]["sub_columns"]
            assert [cell["when"] for cell in cells] == [sub["when"] for sub in sub_columns]
            assert any(cell["value"] is not None for cell in cells)


# -- regenerate and diff ---------------------------------------------------------------------------


def test_services_v1_regenerates_byte_for_byte() -> None:
    expected = (REFERENCE_DIR / "services" / "v1.yaml").read_text(encoding="utf-8")
    assert import_services.render_services() == expected


def test_card_schema_v1_regenerates_byte_for_byte_from_card_fields() -> None:
    expected = (REFERENCE_DIR / "card-schema" / "v1.yaml").read_text(encoding="utf-8")
    assert import_card_schema.render_card_schema() == expected


def test_the_manifest_regenerates_byte_for_byte() -> None:
    expected = (REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8")
    assert import_manifest.render_manifest() == expected


def test_the_classifier_regenerates_byte_for_byte() -> None:
    pytest.importorskip("openpyxl", reason="the `tools` dependency group is not installed")
    from tools import import_classifier

    rows_text, columns_text = import_classifier.render()
    assert rows_text == (REFERENCE_DIR / "classifier" / "v046_24.json").read_text(encoding="utf-8")
    assert columns_text == (REFERENCE_DIR / "classifier" / "v046_24.columns.json").read_text(
        encoding="utf-8"
    )


# -- boundaries and the port -----------------------------------------------------------------------

_READERS = ("openpyxl", "docx")


def test_backend_app_never_imports_the_readers() -> None:
    """A-13: the xlsx/docx readers are tools-only; the app and the gate never need them."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "backend" / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in _READERS:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}")
    assert offenders == []


def test_the_six_legacy_ids_resolve_through_the_file_backed_port() -> None:
    catalog = FileReferenceCatalog().catalog()
    assert catalog.pack_ids == ("legacy-r1", "v046_24-r1")
    services = catalog.services("legacy-r1")
    assert services is not None
    for service_id in LEGACY_SERVICE_IDS:
        entry = services.get(service_id)
        assert entry is not None and entry.id == service_id
    record = catalog.record("legacy-r1")
    assert record is not None
    manifest_files = import_manifest.build_manifest()["files"]
    assert record.services_sha256 == manifest_files["services/v1.yaml"]
    assert record.card_schema_sha256 == manifest_files["card-schema/v1.yaml"]
    assert record.classifier is None and record.classifier_sha256 is None
    v2 = catalog.record("v046_24-r1")
    assert v2 is not None
    assert (v2.card_schema, v2.classifier, v2.services) == ("v2", "v046_24", "v1")
    assert v2.card_schema_sha256 == manifest_files["card-schema/v2.yaml"]
    assert v2.classifier_sha256 == manifest_files["classifier/v046_24.json"]


def test_a_pack_that_drifted_from_its_manifest_is_refused(tmp_path: Path) -> None:
    for name in ("manifest.json", *import_manifest.FILES):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REFERENCE_DIR / name).read_bytes())
    (tmp_path / "services" / "v1.yaml").write_text("services: []\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="sha256"):
        load_reference(tmp_path)
