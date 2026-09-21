"""The realtime read path (HLD `40-realtime-protocol.md`, D3, D5, D8).

Four modules, each with one job:

* `effective_role` — §40.1's "effective realtime role" of a connection, and the fold that
  re-derives it on every push for a `FULL_CYCLE_SINGLE_TRAINEE` trainee;
* `redaction` — §40.4, the **one** place a `SessionEvent` becomes a wire envelope for a role.
  Everything downstream of it is already filtered: a field a role may not see is absent from the
  bytes, not merely unrendered (D3);
* `list_events` — `openapi.yaml`'s `listSessionEvents`, the REST twin of the replay;
* `event_stream` — §40.3's subscribe / replay / drain / tail mechanism as an async generator over
  ports, so it is testable with the in-memory fakes and no socket at all.

Nothing here imports `app.api` or `app.infrastructure` (D2): the WebSocket route is a pump that
reads this generator and writes frames.
"""

from __future__ import annotations
