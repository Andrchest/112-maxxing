"""`load_advice_catalog` — G10's default advice per `ScoringCategory` (I7 E54).

* the real `reference/advice/v1.yaml` covers every `ScoringCategory`, each text non-blank and at
  most 300 characters, and is pinned in `reference/manifest.json`;
* `None` for an absent directory, never a raise;
* a malformed pack (unknown category, missing category, blank or over-long text) raises.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from app.domain.enums import ScoringCategory
from app.infrastructure.reference.advice_catalog import AdviceCatalogError, load_advice_catalog

REPO_ROOT = Path(__file__).resolve().parents[4]
REFERENCE_DIR = REPO_ROOT / "reference"


def test_the_real_pack_covers_every_category() -> None:
    catalog = load_advice_catalog(REFERENCE_DIR)
    assert catalog is not None
    assert set(catalog) == set(ScoringCategory)
    for text in catalog.values():
        assert text.strip()
        assert len(text) <= 300


def test_pinned_in_the_manifest_with_the_right_sha256() -> None:
    manifest = json.loads((REFERENCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    path = REFERENCE_DIR / "advice" / "v1.yaml"
    assert manifest["files"]["advice/v1.yaml"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_absent_directory_is_none_not_a_raise(tmp_path: Path) -> None:
    assert load_advice_catalog(tmp_path) is None


def test_unknown_category_raises(tmp_path: Path) -> None:
    (tmp_path / "advice").mkdir()
    (tmp_path / "advice" / "v1.yaml").write_text(
        "categories:\n  NOT_A_CATEGORY: some text\n", encoding="utf-8"
    )
    with pytest.raises(AdviceCatalogError):
        load_advice_catalog(tmp_path)


def test_missing_category_raises(tmp_path: Path) -> None:
    (tmp_path / "advice").mkdir()
    (tmp_path / "advice" / "v1.yaml").write_text(
        "categories:\n  CARD_QUALITY: some text\n", encoding="utf-8"
    )
    with pytest.raises(AdviceCatalogError):
        load_advice_catalog(tmp_path)


def test_over_long_text_raises(tmp_path: Path) -> None:
    (tmp_path / "advice").mkdir()
    lines = "\n".join(f"  {category.value}: {'x' * 301}" for category in ScoringCategory)
    (tmp_path / "advice" / "v1.yaml").write_text(f"categories:\n{lines}\n", encoding="utf-8")
    with pytest.raises(AdviceCatalogError):
        load_advice_catalog(tmp_path)


def test_blank_text_raises(tmp_path: Path) -> None:
    (tmp_path / "advice").mkdir()
    lines = "\n".join(f"  {category.value}: text" for category in ScoringCategory)
    lines = lines.replace("text", "   ", 1)
    (tmp_path / "advice" / "v1.yaml").write_text(f"categories:\n{lines}\n", encoding="utf-8")
    with pytest.raises(AdviceCatalogError):
        load_advice_catalog(tmp_path)
