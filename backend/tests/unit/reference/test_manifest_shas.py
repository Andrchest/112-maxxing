"""The reference pack is exactly what its manifest pins (HLD 70 §70.6.1, D18) — stdlib only.

The gate's sha check: every file `reference/manifest.json` lists has that sha256, every source a
generated file was built from still has the sha256 recorded for it, and every pack names files the
manifest pins. Nothing here needs the xlsx reader or the application: `json`, `hashlib` and
`pathlib`, so it runs in any environment the gate runs in.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_DIR = REPO_ROOT / "reference"
MANIFEST = json.loads((REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_manifest_has_the_hld_shape() -> None:
    assert MANIFEST["manifest_version"] == 1
    assert set(MANIFEST) == {"manifest_version", "packs", "files", "sources"}
    assert MANIFEST["packs"], "at least one pack"


def test_every_reference_file_has_the_sha256_the_manifest_pins() -> None:
    wrong = {
        name: (_sha256(REFERENCE_DIR / name), expected)
        for name, expected in MANIFEST["files"].items()
        if not (REFERENCE_DIR / name).is_file() or _sha256(REFERENCE_DIR / name) != expected
    }
    assert not wrong, f"reference files drifted from reference/manifest.json: {wrong}"


def test_every_file_under_reference_is_pinned() -> None:
    on_disk = {
        path.relative_to(REFERENCE_DIR).as_posix()
        for path in REFERENCE_DIR.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    assert on_disk == set(MANIFEST["files"])


def test_every_source_has_the_sha256_the_manifest_records() -> None:
    wrong = {}
    for name, source in MANIFEST["sources"].items():
        assert name in MANIFEST["files"], f"source recorded for an unpinned file {name}"
        assert set(source) == {"path", "sha256", "tool"}
        path = REPO_ROOT / source["path"]
        if not path.is_file() or _sha256(path) != source["sha256"]:
            wrong[name] = source["path"]
    assert not wrong, f"sources changed since the reference files were generated: {wrong}"


def test_every_pack_names_pinned_files() -> None:
    files = set(MANIFEST["files"])
    for pack_id, pack in MANIFEST["packs"].items():
        assert set(pack) == {"card_schema", "services", "classifier"}, pack_id
        assert f"card-schema/{pack['card_schema']}.yaml" in files, pack_id
        assert f"services/{pack['services']}.yaml" in files, pack_id
        if pack["classifier"] is not None:
            assert f"classifier/{pack['classifier']}.json" in files, pack_id
            assert f"classifier/{pack['classifier']}.columns.json" in files, pack_id
