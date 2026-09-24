#!/usr/bin/env python3
"""«СЛУЖБЫ 112» → `reference/services/v1.yaml`, the service catalog (HLD 70 §70.6.3, D18, A-6).

The organizer's `СЛУЖБЫ 112.docx` holds no text list — only 55 screenshots of the «Добавьте
службы» picker. Its content therefore enters the repo as a hand transcription of every frame,
`reference/services/sluzhby-112.transcription.tsv` (columns `frame`, `short_name_ru`,
`full_name_ru`, one row per entry, on-screen order). This tool is stdlib + PyYAML only; it reads
that transcription, puts the six legacy ids first (§70.6.3) and classifies every other entry by
the naming patterns of REQ-3042/REQ-3043 (`requirements/normalized/SRC-001-domain-docs.md`):

* `Служба 10N (…)` — the three-digit hotline services: `kind: CITY`, `code: "10N"`; 101-104 are
  the legacy ids `FIRE_RESCUE`, `POLICE`, `AMBULANCE`, `GAS_SERVICE`, so they are not repeated;
* `Поселение <ОКРУГ> (ДДС префектуры … административного округа …)` — `kind: PREFECTURE`,
  `okrug`, id `DDS_PREFECTURE_<OKRUG>`;
* `Поселение <name> (ДДС района / поселения / городского округа …)` and `Упр. района <name> (…)` —
  `kind: DISTRICT`, `district`, id `DDS_DISTRICT_<NAME>`;
* `ГБУ АД <ОКРУГ> (ГБУ Автодороги <ОКРУГ>)` — `kind: CITY`, `okrug`, id `GBU_AD_<OKRUG>`;
* a name starting «Деп.», «Департамент» or «Комитет» (short or full) — `kind: DEPARTMENT`;
* everything else — `kind: CITY`, id from `CITY_IDS` below (UPPER_SNAKE, §70.6.3).

`okrug` of a district is not in its picker entry, so it stays `null` (no geography is invented).
`classifier_org_id` links an entry to its routing column group in
`reference/classifier/v046_24.columns.json` where the column names the same organisation.

    uv run python backend/tools/import_services.py           # write services/v1.yaml + manifest
    uv run python backend/tools/import_services.py --check   # exit 1 when services/v1.yaml is stale
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

if __package__ in (None, ""):  # run as a script: make `tools.*` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.import_manifest import REFERENCE_DIR, REPO_ROOT, TRANSCRIPTION_FILE, write_manifest

CATALOG_ID = "v1"
SERVICES_PATH = REFERENCE_DIR / "services" / f"{CATALOG_ID}.yaml"
TRANSCRIPTION_PATH = REFERENCE_DIR / TRANSCRIPTION_FILE
TRANSCRIPTION_HEADER = ("frame", "short_name_ru", "full_name_ru")


@dataclass(frozen=True)
class TranscribedEntry:
    frame: int
    short_name_ru: str
    full_name_ru: str


#: The six legacy ids, verbatim and first (§70.6.3). `name_ru` is the label the product shows for
#: each today (`frontend/src/shared/i18n/ru.ts` `serviceType*`); `code` ties 101-104 to their
#: «Служба 10N» picker entries, whose parenthesis becomes `full_name_ru`.
LEGACY: tuple[dict[str, Any], ...] = (
    {"id": "FIRE_RESCUE", "name_ru": "Пожарно-спасательная служба", "code": "101"},
    {"id": "POLICE", "name_ru": "Полиция", "code": "102"},
    {
        "id": "AMBULANCE",
        "name_ru": "Скорая медицинская помощь",
        "code": "103",
        "status_policy": "NO_REFUSAL",
    },
    {"id": "GAS_SERVICE", "name_ru": "Газовая служба", "code": "104"},
    # The demo's wrong-but-plausible fifth choice (C8): kept so stored data stays valid, hidden
    # from the v2 picker.
    {"id": "UTILITY_EMERGENCY", "name_ru": "Аварийная коммунальная служба", "deprecated": True},
    {"id": "EDDS", "name_ru": "РЕДДС"},
)

#: Picker short name → catalog id, for every entry that is neither a hotline service, a ДДС nor a
#: «ГБУ АД» road-maintenance entry. A new transcribed entry without an id here fails the build.
CITY_IDS: dict[str, str] = {
    "ФСБ": "FSB",
    "ЦЭМП": "TSEMP",
    "ОГДЦ": "OGDTS",
    "ЦОДД": "TSODD",
    "Гормост": "GORMOST",
    "Мосгортранс": "MOSGORTRANS",
    "Автодороги": "AVTODOROGI",
    "Мосводоканал": "MOSVODOKANAL",
    "Россети МР": "ROSSETI_MR",
    "МОЭК": "MOEK",
    "Деп. ЖКХ": "DEP_ZHKH",
    "Метро": "METRO",
    "АСУ НС": "ASU_NS",
    "Мос.Без.": "MOSBEZ",
    "112 Мос. обл.": "REGION_112_MOSCOW_OBLAST",
    "ФГУП РСВО": "RSVO",
    "ОЭК": "OEK",
    "Мослифт": "MOSLIFT",
    "Мосводосток": "MOSVODOSTOK",
    "Москоллектор": "MOSKOLLEKTOR",
    "Воен. комендатура": "MILITARY_COMMANDANT",
    "ОАТИ": "OATI",
    "ГБУ МСППН": "MSPPN",
    "МЖД": "MZHD",
    "112 Кал. обл.": "REGION_112_KALUGA_OBLAST",
    "Деп. Обр.": "DEP_EDUCATION",
    "Деп. природопользования": "DEP_PPIOOS",
    "МГТС": "MGTS",
    "Канал им. Москвы": "KANAL_IMENI_MOSKVY",
    "Деп. труда и соц.защиты": "DEP_TSZN",
    "ЭВАЖД": "EVAZHD",
    "Дежурно-диспетчерская служба": "DUTY_DISPATCH_SERVICE",
    "Центррегионводхоз": "TSENTRREGIONVODKHOZ",
    "Мособлгаз": "MOSOBLGAZ",
    "Департамент культуры города Москвы": "DEP_CULTURE",
    "ГКУ ЦСА": "GKU_TSSA",
    "Мостуризм": "MOSTURIZM",
    "Департамент строительства": "DEP_CONSTRUCTION",
    "Комитет ветеринарии": "COMMITTEE_VETERINARY",
    "Мосжилинспекция": "MOSZHILINSPEKTSIYA",
}

#: Catalog id → the org id of the classifier column group that names the same organisation
#: (`import_classifier.ORGS`). Entries absent here have no column of their own (`null`); district
#: and prefecture ДДС are reached through «Территориальные ОИВ» (§70.6.4), not a column.
CLASSIFIER_ORG_IDS: dict[str, str] = {
    "FIRE_RESCUE": "MCHS_SLUZHBA_101",
    "POLICE": "MVD",
    "AMBULANCE": "SMP",
    "GAS_SERVICE": "MOSGAZ",
    "FSB": "FSB",
    "TSEMP": "TSEMP",
    "TSODD": "TSODD",
    "GORMOST": "GORMOST",
    "MOSGORTRANS": "MOSGORTRANS",
    "AVTODOROGI": "AVTODOROGI",
    "MOSVODOKANAL": "MOSVODOKANAL",
    "ROSSETI_MR": "MOESK",
    "MOEK": "MOEK",
    "DEP_ZHKH": "DEP_ZHKH",
    "METRO": "METRO",
    "MOSBEZ": "DEP_RBIPK",
    "RSVO": "RSVO",
    "OEK": "OEK",
    "MOSLIFT": "MOSLIFT",
    "MOSVODOSTOK": "MOSVODOSTOK",
    "MOSKOLLEKTOR": "MOSKOLLEKTOR",
    "MILITARY_COMMANDANT": "MILITARY_COMMANDANT",
    "OATI": "OATI",
    "MSPPN": "MSPPN",
    "MZHD": "RZHD",
    "DEP_EDUCATION": "DEP_EDUCATION",
    "DEP_PPIOOS": "DEP_PPIOOS",
    "MGTS": "MGTS",
    "KANAL_IMENI_MOSKVY": "KANAL_IMENI_MOSKVY",
    "DEP_TSZN": "DEP_TSZN",
    "EVAZHD": "EVAZHD",
    "TSENTRREGIONVODKHOZ": "TSENTRREGIONVODKHOZ",
    "MOSOBLGAZ": "MOSOBLGAZ",
    "DEP_CULTURE": "DEP_CULTURE",
    "GKU_TSSA": "GKU_TSSA",
    "MOSTURIZM": "MOSTURIZM",
    "DEP_CONSTRUCTION": "DEP_CONSTRUCTION",
    "COMMITTEE_VETERINARY": "COMMITTEE_VETERINARY",
    "MOSZHILINSPEKTSIYA": "MOSZHILINSPEKTSIYA",
}

_HOTLINE = re.compile(r"^Служба (1\d\d)$")
_PREFECTURE = re.compile(r"^ДДС префектур")
_DDS = re.compile(r"^ДДС ")
_ROAD_OKRUG = re.compile(r"^ГБУ АД (\S+)$")
_DEPARTMENT_PREFIXES = ("Деп.", "Департамент", "Комитет")
_DISTRICT_PREFIXES = ("Поселение ", "Упр. района ")

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip


def transliterate_id(name_ru: str) -> str:
    """`Чертаново Северное` → `CHERTANOVO_SEVERNOE` (UPPER_SNAKE, §70.6.3)."""
    latin = "".join(_TRANSLIT.get(char, char) for char in name_ru.lower())
    return re.sub(r"[^a-z0-9]+", "_", latin).strip("_").upper()


def read_transcription(path: Path = TRANSCRIPTION_PATH) -> list[TranscribedEntry]:
    """Every data row of the transcription (comment lines `# …` and the header skipped)."""
    entries: list[TranscribedEntry] = []
    header_seen = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line or line.startswith("#"):
            continue
        cells = line.split("\t")
        if not header_seen:
            if tuple(cells) != TRANSCRIPTION_HEADER:
                raise ValueError(f"{path}:{number}: header must be {TRANSCRIPTION_HEADER}")
            header_seen = True
            continue
        if len(cells) != len(TRANSCRIPTION_HEADER) or not cells[1]:
            raise ValueError(f"{path}:{number}: expected frame, short_name_ru, full_name_ru")
        entries.append(TranscribedEntry(int(cells[0]), cells[1], cells[2]))
    return entries


def _entry(
    service_id: str,
    name_ru: str,
    full_name_ru: str,
    kind: str,
    *,
    code: str | None = None,
    okrug: str | None = None,
    district: str | None = None,
    status_policy: str = "DEFAULT",
    deprecated: bool = False,
) -> dict[str, Any]:
    return {
        "id": service_id,
        "name_ru": name_ru,
        "full_name_ru": full_name_ru,
        "kind": kind,
        "code": code,
        "okrug": okrug,
        "district": district,
        "classifier_org_id": CLASSIFIER_ORG_IDS.get(service_id),
        "status_policy": status_policy,
        "display": True,
        "deprecated": deprecated,
        "phone": None,
    }


def _strip_prefix(name: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def classify(entry: TranscribedEntry) -> dict[str, Any]:
    """One catalog entry for one transcribed picker entry (not a 101-104 hotline service)."""
    short, full = entry.short_name_ru, entry.full_name_ru or entry.short_name_ru
    if (hotline := _HOTLINE.match(short)) is not None:
        code = hotline.group(1)
        return _entry(f"SERVICE_{code}", short, full, "CITY", code=code)
    if _PREFECTURE.match(full):
        okrug = _strip_prefix(short, _DISTRICT_PREFIXES)
        return _entry(
            f"DDS_PREFECTURE_{transliterate_id(okrug)}", short, full, "PREFECTURE", okrug=okrug
        )
    if _DDS.match(full):
        district = _strip_prefix(short, _DISTRICT_PREFIXES)
        return _entry(
            f"DDS_DISTRICT_{transliterate_id(district)}", short, full, "DISTRICT", district=district
        )
    if (road := _ROAD_OKRUG.match(short)) is not None:
        okrug = road.group(1)
        return _entry(f"GBU_AD_{transliterate_id(okrug)}", short, full, "CITY", okrug=okrug)
    service_id = CITY_IDS.get(short)
    if service_id is None:
        raise ValueError(f"frame {entry.frame}: no catalog id for «{short}»; add it to CITY_IDS")
    kind = (
        "DEPARTMENT"
        if short.startswith(_DEPARTMENT_PREFIXES) or full.startswith(_DEPARTMENT_PREFIXES)
        else "CITY"
    )
    return _entry(service_id, short, full, kind)


def build_catalog(entries: list[TranscribedEntry]) -> list[dict[str, Any]]:
    """The six legacy ids first, then every transcribed entry in on-screen order."""
    by_code = {
        match.group(1): entry
        for entry in entries
        if (match := _HOTLINE.match(entry.short_name_ru)) is not None
    }
    catalog: list[dict[str, Any]] = []
    for legacy in LEGACY:
        code = legacy.get("code")
        picker = by_code.get(code) if code is not None else None
        full_name = picker.full_name_ru if picker is not None else legacy["name_ru"]
        catalog.append(
            _entry(
                legacy["id"],
                legacy["name_ru"],
                full_name,
                "CITY",
                code=code,
                status_policy=legacy.get("status_policy", "DEFAULT"),
                deprecated=legacy.get("deprecated", False),
            )
        )
    legacy_codes = {legacy["code"] for legacy in LEGACY if "code" in legacy}
    for entry in entries:
        hotline = _HOTLINE.match(entry.short_name_ru)
        if hotline is not None and hotline.group(1) in legacy_codes:
            continue
        catalog.append(classify(entry))
    ids = [item["id"] for item in catalog]
    duplicates = sorted({service_id for service_id in ids if ids.count(service_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate catalog ids: {duplicates}")
    return catalog


def render_services(transcription: Path = TRANSCRIPTION_PATH) -> str:
    """The byte-stable `services/v1.yaml` for the transcription on disk."""
    document = {
        "catalog_id": CATALOG_ID,
        "source": {
            "transcription": f"reference/{TRANSCRIPTION_FILE}",
            "requirements": ["REQ-3042", "REQ-3043"],
        },
        "services": build_catalog(read_transcription(transcription)),
    }
    header = (
        "# Generated by backend/tools/import_services.py from "
        f"reference/{TRANSCRIPTION_FILE} — do not edit by hand.\n"
    )
    return header + yaml.safe_dump(
        document, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Build reference/services/v1.yaml (HLD 70 §70.6.3)"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when services/v1.yaml is stale"
    )
    args = parser.parse_args(argv)
    rendered = render_services()
    if args.check:
        current = SERVICES_PATH.read_text(encoding="utf-8") if SERVICES_PATH.is_file() else ""
        if current != rendered:
            print(
                f"{SERVICES_PATH} is stale; run backend/tools/import_services.py", file=sys.stderr
            )
            return 1
        return 0
    SERVICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVICES_PATH.write_text(rendered, encoding="utf-8")
    write_manifest()
    print(f"wrote {SERVICES_PATH.relative_to(REPO_ROOT)} and the manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
