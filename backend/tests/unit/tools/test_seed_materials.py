"""`app.tools.seed_materials`'s pure parts: reading `organizer.yaml` and its sha256 drift check
(I5 E41 CHANGE B). The DB-backed upload path (idempotency, the `admin` uploader) is
`backend/tests/integration/persistence/test_seed_materials.py`.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from app.tools.seed_materials import (
    OrganizerManifestError,
    OrganizerMaterial,
    _read_verified,
    load_organizer_materials,
)


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_the_packaged_organizer_manifest_loads_and_has_no_duplicate_ids() -> None:
    materials = load_organizer_materials()
    assert materials
    ids = [material.id for material in materials]
    assert len(ids) == len(set(ids))
    for material in materials:
        assert material.title_ru
        assert material.path
        assert len(material.sha256) == 64


def test_every_packaged_organizer_source_matches_its_pinned_sha256() -> None:
    """The three organizer files `organizer.yaml` pins are read-only under `requirements/sources`
    (I5 E41 CHANGE B) — never copied — so this is the drift check the CLI itself also runs."""
    repo_root = Path(__file__).resolve().parents[4]
    for material in load_organizer_materials():
        content = _read_verified(material, repo_root=repo_root)
        assert sha256(content).hexdigest() == material.sha256


def test_duplicate_ids_are_refused(tmp_path: Path) -> None:
    manifest = _write_yaml(
        tmp_path / "organizer.yaml",
        """
materials:
  - id: same
    title_ru: "A"
    path: "a.pdf"
    sha256: "0" * 1
  - id: same
    title_ru: "B"
    path: "b.pdf"
    sha256: "0" * 1
""".replace('"0" * 1', "0" * 64),
    )
    with pytest.raises(OrganizerManifestError, match="duplicate"):
        load_organizer_materials(manifest)


def test_a_missing_source_file_is_refused(tmp_path: Path) -> None:
    material = OrganizerMaterial(
        id="missing", title_ru="Т", path="requirements/sources/does-not-exist.pdf", sha256="0" * 64
    )
    with pytest.raises(OrganizerManifestError, match="not found"):
        _read_verified(material, repo_root=tmp_path)


def test_a_drifted_source_file_is_refused(tmp_path: Path) -> None:
    source_dir = tmp_path / "requirements" / "sources"
    source_dir.mkdir(parents=True)
    source_path = source_dir / "changed.pdf"
    source_path.write_bytes(b"new bytes")
    material = OrganizerMaterial(
        id="changed",
        title_ru="Т",
        path="requirements/sources/changed.pdf",
        sha256=sha256(b"old bytes").hexdigest(),
    )
    with pytest.raises(OrganizerManifestError, match="now, but"):
        _read_verified(material, repo_root=tmp_path)
