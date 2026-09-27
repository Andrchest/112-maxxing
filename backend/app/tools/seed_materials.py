"""`python -m app.tools.seed_materials` — upload the organizer's methodical materials (I5 E41
CHANGE B, HLD 71 §71.11/§71.18.1, Q-E13-2).

Reads `reference/materials/organizer.yaml` (a tracked list naming files under
`requirements/sources/` — read-only, never copied into the repo) and uploads each one through the
I4 E34 `UploadMaterial` use case, exactly as an instructor's own upload would: the same allow-list,
size limit and sha256 dedupe (`app.application.materials.upload_material`).

**Idempotent across runs**, not just within `UploadMaterial`'s own file-dedupe: re-running this
command must not create a second `training_materials` row for the same organizer file, so the
existing rows are read first and a file whose sha256 is already present is skipped.

**Uploader**: the seeded `admin` account (`app.tools.seed_users.SEED_ACCOUNTS`) — "a system or
admin account per the existing seed pattern" (I5 E41 CHANGE B). Run `make seed-users` before this
command; a missing `admin` account is a refusal, not a silent skip.

**Drift check**: each entry's `sha256` in `organizer.yaml` is the file's hash at the moment it was
listed. A file that has changed on disk since then refuses the whole run rather than uploading
silently-different bytes under an old title.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256 as sha256_of
from pathlib import Path

import yaml

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.materials.upload_material import UploadMaterial, UploadMaterialRequest
from app.config.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.infrastructure.clock import SystemClock
from app.infrastructure.ids import Uuid4Generator
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory

__all__ = [
    "OrganizerManifestError",
    "OrganizerMaterial",
    "UploaderNotFoundError",
    "load_organizer_materials",
    "main",
    "seed_materials",
]

#: `backend/app/tools/seed_materials.py` is three levels under the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
ORGANIZER_MANIFEST = REPO_ROOT / "reference" / "materials" / "organizer.yaml"

#: The account `seed_users.py` seeds with the `ADMIN` role (I5 E41 CHANGE B: "a system or admin
#: account per the existing seed pattern").
UPLOADER_USERNAME = "admin"


@dataclass(frozen=True)
class OrganizerMaterial:
    """One `organizer.yaml` entry."""

    id: str
    title_ru: str
    path: str
    sha256: str


class OrganizerManifestError(RuntimeError):
    """`organizer.yaml` is missing/malformed, or a listed source drifted from its pinned sha256."""


class UploaderNotFoundError(RuntimeError):
    """No `admin` account exists yet (`make seed-users` was not run first)."""


def load_organizer_materials(manifest_path: Path = ORGANIZER_MANIFEST) -> list[OrganizerMaterial]:
    """Every entry of `organizer.yaml`, in file order."""
    document = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    entries = document.get("materials") or []
    materials = [
        OrganizerMaterial(
            id=entry["id"],
            title_ru=entry["title_ru"],
            path=entry["path"],
            sha256=entry["sha256"],
        )
        for entry in entries
    ]
    ids = [material.id for material in materials]
    if len(ids) != len(set(ids)):
        raise OrganizerManifestError(f"{manifest_path}: duplicate material ids in {ids}")
    return materials


def _read_verified(material: OrganizerMaterial, repo_root: Path = REPO_ROOT) -> bytes:
    """`material`'s bytes, refusing a source that drifted from its pinned sha256."""
    source = repo_root / material.path
    if not source.is_file():
        raise OrganizerManifestError(f"{material.id}: source file not found at {source}")
    content = source.read_bytes()
    digest = sha256_of(content).hexdigest()
    if digest != material.sha256:
        raise OrganizerManifestError(
            f"{material.id}: {source} is {digest} now, but organizer.yaml pins {material.sha256} "
            "— the organizer source changed since it was listed; re-verify and update the pin"
        )
    return content


class _NullPublisher:
    """An `EventPublisher` that publishes nothing (`app.tools.seed_users`'s own pattern)."""

    async def publish(self, session_id: object, envelopes: object) -> None:
        return None


async def seed_materials(
    settings: Settings,
    materials: Sequence[OrganizerMaterial] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[str, str]]:
    """Upload every organizer material once; returns `(id, outcome)` pairs.

    `outcome` is `"uploaded"` or `"already present"` — the second one is what makes running this
    command twice against the same database a no-op the second time. `repo_root` resolves each
    entry's `path`; it is only ever overridden by tests (`test_seed_materials.py`'s idempotency
    test points it at a scratch directory instead of the real `requirements/sources`).
    """
    entries = list(materials) if materials is not None else load_organizer_materials()
    engine = create_engine(settings)
    try:
        unit_of_work = unit_of_work_factory(
            create_session_factory(engine), SystemClock(), _NullPublisher()
        )
        async with unit_of_work() as uow:
            admin = await uow.users.get_by_username(UPLOADER_USERNAME)
            if admin is None:
                raise UploaderNotFoundError(
                    f"no {UPLOADER_USERNAME!r} account — run `make seed-users` first"
                )
            existing = await uow.materials.list_materials(include_archived=True)
            await uow.commit()
        existing_sha256 = {row.sha256 for row in existing}

        actor = AuthenticatedUser(
            user_id=admin.user_id,
            username=admin.username,
            display_name_ru=admin.display_name_ru,
            user_role=admin.user_role,
        )
        upload_material = UploadMaterial(
            unit_of_work,
            Uuid4Generator(),
            SystemClock(),
            materials_dir=Path(settings.data_dir) / "materials",
            max_size_bytes=settings.material_max_mb * 1024 * 1024,
        )

        results: list[tuple[str, str]] = []
        for entry in entries:
            content = _read_verified(entry, repo_root=repo_root)
            digest = sha256_of(content).hexdigest()
            if digest in existing_sha256:
                results.append((entry.id, "already present"))
                continue
            await upload_material(
                UploadMaterialRequest(
                    title_ru=entry.title_ru,
                    file_name=Path(entry.path).name,
                    content=content,
                ),
                actor=actor,
            )
            existing_sha256.add(digest)
            results.append((entry.id, "uploaded"))
        return results
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Prints one `<id>: <outcome>` line per organizer material."""
    parser = argparse.ArgumentParser(description="Upload the organizer materials (I5 E41)")
    parser.parse_args(argv)
    try:
        results = asyncio.run(seed_materials(get_settings()))
    except (OrganizerManifestError, UploaderNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for material_id, outcome in results:
        print(f"{material_id}: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
