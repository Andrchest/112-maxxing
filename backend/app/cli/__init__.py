"""`app.cli` — the operational CLI package (SPEC §38, §9.2; HLD `60-inference-ops.md` §5; R7, R8).

One package, two sub-commands, dispatched by `backend/app/cli/__main__.py`:

* `preflight` (`app.cli.preflight`) — the twelve SPEC §38 checks, loads no ML model;
* `purge_recordings` (`app.cli.purge_recordings`) — the retention purge, shared with
  `purgeRecordings` (`POST /api/v1/admin/recordings/purge`).

`python -m app.cli <sub-command> [args...]`.
"""

from __future__ import annotations
