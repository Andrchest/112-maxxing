"""The handoff and the role transition (E9, SPEC §10, §13, §42 item 3; §10.7-§10.9; D3, D5, D6, D8).

The three operations that carry a session across the seam between its two trainee roles, plus the
two pieces of machinery they share:

| module | operation | `x-action` |
|:--|:--|:--|
| `create_handoff` | `createHandoff` | `create_handoff` |
| `complete_operator_stage` | `completeOperatorStage` | `complete_stage` |
| `continue_to_next_stage` | `continueToNextStage` | `finish_role_transition` |
| `complete_session` | — (the `complete` trigger, with the real `total_events`) | — |
| `prefab_handoff` | — (the DDS-only chain's scenario-authored handoff, D6) | — |
| `work_item` | the `DdsWorkItem` projection `getDdsWorkItem` / `SessionSnapshot` answer with | — |

`createHandoff` and `completeOperatorStage` run through the one Operator 112 command pipeline
(`app.application.operator.command_context`); `continueToNextStage` cannot, and says why in its
own docstring.

**INV 3 (SPEC §42 item 3) is this package's structural property.** Nothing here — no module, no
constructor, no function signature — names a world-truth or caller-belief repository or type, so
the DDS side has no path to the values the operator did not enter. `work_item` in particular is a
pure function of a `HandoffSnapshot` and its `DDSAssignment` legs.
`backend/tests/invariants/test_inv_03_dds_never_reads_world_truth.py` asserts both halves: the
scan of this package's source, and a full 112 -> DDS run over HTTP in which the operator types the
caller's wrong house number and the DDS payloads carry it unrepaired.

Deliberately **no re-exports**. `app.application.sessions.start_session` imports
`prefab_handoff` — a DDS-only chain's handoff is materialised when the session starts — and every
other module here reaches back into `app.application.sessions`, so a package `__init__` that
imported them would close an import cycle through `start_session`. The composition root imports
the concrete modules by path, exactly as it does for `app.application.operator`, so nothing is
lost but the index.
"""

from __future__ import annotations
