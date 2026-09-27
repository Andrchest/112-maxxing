#!/usr/bin/env python3
"""`reference/manifest.json` — the reference-pack manifest (HLD `70-i3-alignment.md` §70.6.1, D18).

The manifest names the packs, pins the sha256 of every reference file and the sha256 of the
organizer source each generated file was built from. It is written by the three generators
(`import_card_schema.py`, `import_services.py`, `import_classifier.py`) after they write their
files, and can be rebuilt on its own:

    uv run python backend/tools/import_manifest.py           # rewrite reference/manifest.json
    uv run python backend/tools/import_manifest.py --check   # exit 1 when it is stale

Stdlib only: the gate's sha check (`backend/tests/unit/reference/test_reference_pack.py`) reads
the same file with `json` + `hashlib` and needs nothing from here.

Scope: `legacy-r1` (card `v1`, no classifier) since I3 E2a; `v046_24-r1` (card `v2`, classifier
`v046_24`) since E3a added `card-schema/v2.yaml` (HLD 70 §70.6.1, B1 §3 "Row E3a′"), re-pinned with
the ДДС phone's personas (`personas/v1.yaml`, hand authored) by I3 E6c (HLD 80 §80.4.1). A pack
without personas names none (`legacy-r1`: schema 1 never has the phone, P5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "reference"
MANIFEST_PATH = REFERENCE_DIR / "manifest.json"
MANIFEST_VERSION = 1

#: Pack id → the file ids it is made of. Order matters: the last pack is "the newest pack in the
#: manifest", the reference API's default (`PackQueryParam`).
PACKS: dict[str, dict[str, str | None]] = {
    "legacy-r1": {"card_schema": "v1", "services": "v1", "classifier": None},
    "v046_24-r1": {
        "card_schema": "v2",
        "services": "v1",
        "classifier": "v046_24",
        "personas": "v1",
    },
}

#: Every reference file the manifest pins, in the order HLD 70 §70.6.1 lists them.
FILES: tuple[str, ...] = (
    "card-schema/v1.yaml",
    "card-schema/v2.yaml",
    "card-schema/conditions.fixtures.json",
    "classifier/v046_24.json",
    "classifier/v046_24.columns.json",
    "services/v1.yaml",
    "services/sluzhby-112.transcription.tsv",
    "personas/v1.yaml",
    # I4 E35 (HLD 71 §71.12, D35): `text_quality`'s data — no pack names these (they are read by
    # `TextCheckerPort`, not `ReferencePort`'s pack machinery), but every file under `reference/`
    # is pinned here regardless (`test_every_file_under_reference_is_pinned`). Fetched verbatim
    # from an external URL, like `personas/v1.yaml` is hand-authored: no `SOURCES` entry, because
    # there is no repo-local organizer file to re-derive them from.
    "lexicon/ru_RU.aff",
    "lexicon/ru_RU.dic",
    "lexicon/README_ru_RU.txt",
    "lexicon/SOURCES.txt",
    "streets/osm_moscow_street_names.txt",
    "streets/SOURCES.txt",
    # I5 E41 (Q-E23-2, CHANGE A): the ФНС КЛАДР half of `StreetDirectory`'s union (region 77,
    # Moscow). Also fetched verbatim from an external source with nothing repo-local to re-derive
    # it from — the raw `base.7z` archive is not committed (`backend/tools/import_kladr_streets.py`)
    # — so it gets no `SOURCES` entry either, same as the OSM extract above.
    "streets/kladr_moscow_street_names.txt",
    # I5 E41 (CHANGE B, Q-E13-2): the organizer materials list `seed-materials` uploads from.
    # Points at files under `requirements/sources/05-organizer-materials` (read-only, not copied)
    # — pinned here as a plain reference-directory file even though it names no bytes copied under
    # `reference/` (its own sha is what `test_every_reference_file_has_the_sha256_the_manifest_pins`
    # checks; the sources it points to are verified by `app.tools.seed_materials` itself, not here).
    "materials/organizer.yaml",
)

CLASSIFIER_SOURCE = (
    "requirements/sources/05-organizer-materials/"
    "Классификатор_происшествий_v_046_24_корректировка_МВД_+_Департамент (1).xlsx"
)
SERVICES_SOURCE = "requirements/sources/01-qna-session-telegram/files/СЛУЖБЫ 112.docx"
CARD_SOURCE = "requirements/sources/01-qna-session-telegram/files/КАРТОЧКА 112.docx"
TRANSCRIPTION_FILE = "services/sluzhby-112.transcription.tsv"

#: Reference file → the source it is built from (repo-relative) and what builds it. The services
#: catalog is two steps: the organizer docx holds only picker screenshots, so a hand transcription
#: of every frame (`services/sluzhby-112.transcription.tsv`) is the source `import_services.py`
#: reads; the transcription's own source is the docx. Both shas are recorded, so a change to either
#: the screenshots or the transcription is caught by the gate.
SOURCES: dict[str, tuple[str, str]] = {
    "card-schema/v2.yaml": (
        CARD_SOURCE,
        "hand authoring (I3 E3a; also «СКРИНШОТ КАРТОЧКИ 112ГСИ.docx»)",
    ),
    "classifier/v046_24.json": (CLASSIFIER_SOURCE, "backend/tools/import_classifier.py"),
    "classifier/v046_24.columns.json": (CLASSIFIER_SOURCE, "backend/tools/import_classifier.py"),
    "services/v1.yaml": (
        f"reference/{TRANSCRIPTION_FILE}",
        "backend/tools/import_services.py (+ reference/classifier/v046_24.columns.json)",
    ),
    TRANSCRIPTION_FILE: (SERVICES_SOURCE, "hand transcription (I3 E2a)"),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_manifest(
    reference_dir: Path = REFERENCE_DIR, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """The manifest document for the files currently on disk."""
    files = {name: sha256_file(reference_dir / name) for name in FILES}
    sources = {
        name: {"path": path, "sha256": sha256_file(repo_root / path), "tool": tool}
        for name, (path, tool) in SOURCES.items()
    }
    return {
        "manifest_version": MANIFEST_VERSION,
        "packs": {pack_id: dict(parts) for pack_id, parts in PACKS.items()},
        "files": files,
        "sources": sources,
    }


def render_manifest(reference_dir: Path = REFERENCE_DIR, repo_root: Path = REPO_ROOT) -> str:
    """Byte-stable JSON: two-space indent, UTF-8 kept, one trailing newline."""
    document = build_manifest(reference_dir, repo_root)
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_manifest() -> None:
    """Rewrite the manifest once every pinned file exists (a first build writes them in turn)."""
    missing = [name for name in FILES if not (REFERENCE_DIR / name).is_file()]
    if missing:
        print(f"manifest not written yet; missing: {', '.join(missing)}", file=sys.stderr)
        return
    MANIFEST_PATH.write_text(render_manifest(), encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Rebuild reference/manifest.json (HLD 70 §70.6.1)")
    parser.add_argument("--check", action="store_true", help="exit 1 when the manifest is stale")
    args = parser.parse_args(argv)
    if args.check:
        current = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.is_file() else ""
        if current != render_manifest():
            print(
                f"{MANIFEST_PATH} is stale; run backend/tools/import_manifest.py", file=sys.stderr
            )
            return 1
        return 0
    MANIFEST_PATH.write_text(render_manifest(), encoding="utf-8")
    print(f"wrote {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
