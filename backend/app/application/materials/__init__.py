"""`app.application.materials` — the methodical-materials reference base (HLD 71 §71.11, I4 E34).

Four use cases: `UploadMaterial`, `ListMaterials`, `GetMaterialFile`, `ArchiveMaterial`. Metadata
lives in `training_materials` (`app.application.ports.material_repository`); the bytes live at
`Settings.data_dir/materials/<sha256>`, read and written directly by these use cases with plain
`pathlib.Path` I/O — the same choice `app.application.recording.purge_recordings` makes for the
recordings directory (D2 forbids importing `app.infrastructure`, not stdlib file I/O).
"""

from __future__ import annotations
