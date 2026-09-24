"""File-backed `ReferencePort` (HLD `70-i3-alignment.md` §70.6.1, D18).

Reads `reference/manifest.json` and the files it pins, checks every file's sha256 against the
manifest (a pack that drifted from its manifest is refused, not half-used), and builds one
immutable `ReferenceCatalog`. Loading is lazy — the first `catalog()` call — and cached per
directory for the process, so building many containers (the API tests do) parses the ~2.6 MB
classifier once.

The default directory is `reference/` at the repository root (beside `scenarios/`), resolved from
this module's location.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import yaml

from app.domain.routing.catalog import (
    ReferenceCatalog,
    ReferencePack,
    ServiceCatalog,
)
from app.domain.routing.classifier import Classifier, ClassifierOrg

__all__ = ["DEFAULT_REFERENCE_DIR", "FileReferenceCatalog", "ReferencePackError", "load_reference"]

DEFAULT_REFERENCE_DIR = Path(__file__).resolve().parents[4] / "reference"
"""`<repo>/reference` — `backend/app/infrastructure/reference/file_catalog.py` is four levels in."""


class ReferencePackError(RuntimeError):
    """The reference directory is missing, malformed, or disagrees with its manifest."""


_CACHE: dict[Path, ReferenceCatalog] = {}
_LOCK = threading.Lock()


class FileReferenceCatalog:
    """`ReferencePort` over a `reference/` directory."""

    def __init__(self, directory: Path | str = DEFAULT_REFERENCE_DIR) -> None:
        self._directory = Path(directory).resolve()

    @property
    def directory(self) -> Path:
        return self._directory

    def catalog(self) -> ReferenceCatalog:
        with _LOCK:
            cached = _CACHE.get(self._directory)
            if cached is None:
                cached = load_reference(self._directory)
                _CACHE[self._directory] = cached
            return cached


def load_reference(directory: Path) -> ReferenceCatalog:
    """Parse and sha-check the pack at `directory`."""
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ReferencePackError(f"{manifest_path} does not exist")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    files: dict[str, str] = dict(manifest.get("files", {}))
    for name, expected in files.items():
        path = directory / name
        if not path.is_file():
            raise ReferencePackError(f"{path} is pinned by the manifest but missing")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ReferencePackError(f"{path}: sha256 {actual} != manifest {expected}")

    packs = [
        ReferencePack(pack_id=pack_id, **parts) for pack_id, parts in manifest["packs"].items()
    ]
    service_ids = sorted({pack.services for pack in packs})
    classifier_ids = sorted({pack.classifier for pack in packs if pack.classifier is not None})
    return ReferenceCatalog(
        packs=packs,
        service_catalogs=[_services(directory, files, catalog_id) for catalog_id in service_ids],
        classifiers=[_classifier(directory, files, cid) for cid in classifier_ids],
        file_sha256=files,
        manifest=manifest,
    )


def _pinned(directory: Path, files: dict[str, str], name: str) -> Path:
    if name not in files:
        raise ReferencePackError(f"{name} is used by a pack but not pinned in the manifest")
    return directory / name


def _services(directory: Path, files: dict[str, str], catalog_id: str) -> ServiceCatalog:
    path = _pinned(directory, files, f"services/{catalog_id}.yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ServiceCatalog(catalog_id=catalog_id, services=document["services"])


def _classifier(directory: Path, files: dict[str, str], classifier_id: str) -> Classifier:
    rows_path = _pinned(directory, files, f"classifier/{classifier_id}.json")
    columns_path = _pinned(directory, files, f"classifier/{classifier_id}.columns.json")
    rows = json.loads(rows_path.read_text(encoding="utf-8"))["rows"]
    columns = json.loads(columns_path.read_text(encoding="utf-8"))
    orgs = [ClassifierOrg(org_id=org_id, **org) for org_id, org in columns["orgs"].items()]
    return Classifier(classifier_id=classifier_id, rows=rows, orgs=orgs)
