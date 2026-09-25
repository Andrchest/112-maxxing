"""S5 admin monitoring backend (I4 E29; `docs/hld/71-i4-wave4.md` §71.6).

The administrator's read side: `listAuditLog` (via `AuditReader`, E25's own port — nothing to add
here), `getUsageStats`, `getServerLoad`, `getErrorReport`, `listAdminAlerts` and `getBackupStatus`;
plus the `purgeRecordings` `409 BACKUP_REQUIRED` guard, which lives on `PurgeRecordings` itself
(`app.application.recording.purge_recordings`) rather than here, since it is the same use case
`python -m app.cli purge_recordings` calls (R8 of E18).

One module per operation, each its own use case class, mirroring `app.application.reports`.
"""

from __future__ import annotations
