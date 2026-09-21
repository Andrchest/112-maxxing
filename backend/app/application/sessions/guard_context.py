"""Projecting `GuardRuntime` from the event log (HLD `10-domain-model.md` §10.8, D5).

A domain guard is pure: every fact it cannot derive from the session aggregate arrives on
`GuardContext.runtime`. `build_guard_runtime` is the one place that derives those facts, and it
derives them from the audit source — the `session_events` log — rather than from any materialised
projection, because the log is authoritative (SPEC §8, §31).

It is a pure function over a `Sequence[SessionEvent]`: no repository, no clock, no I/O. The four
facts the log cannot answer (`scenario_valid`, `inference_ready`, `transport_ready`,
`resolution_condition_met`) are keyword arguments the calling use case supplies from its own
ports.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.common.state_machine import GuardRuntime
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType

__all__ = ["build_guard_runtime"]


def build_guard_runtime(
    events: Sequence[SessionEvent],
    *,
    scenario_valid: bool,
    inference_ready: bool,
    transport_ready: bool = False,
    resolution_condition_met: bool = False,
) -> GuardRuntime:
    """Derive the event-log-backed `GuardRuntime` fields for one session (§10.8).

    `events` is the session's log in `seq_no` order, as `EventStore.read` returns it. The derived
    fields:

    * `first_finalized_turn` — some `ASR_FINAL` has been appended (§10.8 `begin_interview`).
    * `call_connected` — the last of `CALL_ANSWERED` / `CALL_ENDED` is `CALL_ANSWERED`.
    * `call_ended` — a `CALL_ENDED` has been appended and no later `CALL_ANSWERED` reopened one.
    * `transition_started_ms` — the `monotonic_offset_ms` of the `ROLE_TRANSITION_STARTED`
      currently in effect, i.e. `None` once the matching `ROLE_TRANSITION_COMPLETED` landed.

    **The log still cannot answer `transport_ready`, and this function still does not try.**
    §10.8's `ring` guard asks whether the call transport can take a call — the LiveKit server is
    reachable and the voice-agent heartbeat is present (E11; see
    `app.application.ports.call_transport_status`) — and the §10.13 event catalog has no event
    that states it. `TRANSPORT_DISCONNECTED` /
    `TRANSPORT_RECONNECTED` describe losing and regaining an already-established transport, not
    establishing one, and `CALL_RINGING` is the *result* of the guarded transition, so deriving it
    from the log here would make the guard vacuous. E7-A turned the missing fact into the
    `app.application.ports.call_transport_status.CallTransportStatus` port, so `transport_ready`
    is now a **keyword the caller supplies from that port**; it defaults to `False`, which denies
    `ring` and is the documented `GuardRuntime` default, for every caller that has no transport
    reading to give. E11 added the `SIM_CALL_TRANSPORT=livekit` adapter behind that port beside
    the `fake` one, so the reading is now a real one wherever LiveKit is wired.
    """
    first_finalized_turn = False
    call_connected = False
    call_ended = False
    transition_started_ms: int | None = None

    for event in events:
        if event.event_type is EventType.ASR_FINAL:
            first_finalized_turn = True
        elif event.event_type is EventType.CALL_ANSWERED:
            call_connected = True
            call_ended = False
        elif event.event_type is EventType.CALL_ENDED:
            call_connected = False
            call_ended = True
        elif event.event_type is EventType.ROLE_TRANSITION_STARTED:
            transition_started_ms = event.monotonic_offset_ms
        elif event.event_type is EventType.ROLE_TRANSITION_COMPLETED:
            transition_started_ms = None

    return GuardRuntime(
        scenario_valid=scenario_valid,
        inference_ready=inference_ready,
        transport_ready=transport_ready,
        first_finalized_turn=first_finalized_turn,
        call_connected=call_connected,
        call_ended=call_ended,
        resolution_condition_met=resolution_condition_met,
        transition_started_ms=transition_started_ms,
    )
