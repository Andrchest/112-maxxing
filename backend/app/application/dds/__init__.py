"""The DDS stage slice — the `/dds/*` operations and the stage's simulation triggers.

Thirteen operations: the eleven of `openapi.yaml`'s `dds` tag plus the two E9 added additively
(`openDdsResourceSelection`, `backToDdsAcknowledged`). `app.application.operator` is the Operator
112 half of the same shape, and this package mirrors it deliberately: one command gate
(`command_context`), one views module, one module per operation, and the events a command appends
are exactly the `x-emits` list `openapi.yaml` gives that operation. Two things are specific to
this side.

**The information boundary is structural (D3, SPEC §42 test 3).** No module under this package
imports `WorldTruth`, `CallerBelief`, the live `OperatorCard` or any of their repositories, and no
service constructed here is given one. The DDS trainee sees what the 112 operator typed — through
the frozen `HandoffSnapshot` and nothing else — plus the resource board, the notifications and the
radio traffic the simulation addressed to them.
`backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` scans every module here.

**One work item, N per-service legs (E9 analyst R1-R7).** `role_stages.state` is the single
authority for the DDS workflow state; each `dds_assignments` row mirrors it and additionally holds
its own `dispatched_at_offset_ms` and its own resource lists. One trainee action therefore produces
exactly **one** trainee event, carrying the primary leg's `assignment_id`; only the
`HANDOFF_RECEIVED` fan-out is N-fold, and it is the handoff slice's (`app.application.handoff`).
Which leg a unit attaches to is decided in one function, `leg_for`.

The package index deliberately re-exports nothing: `app.api.container` imports each use case from
its own module, and a flat index would tempt a cross-import between two command modules that
should only ever share the gate.
"""

from __future__ import annotations

__all__: list[str] = []
