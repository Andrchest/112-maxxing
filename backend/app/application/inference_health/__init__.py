"""Inference health as a *session* concern (HLD `60-inference-ops.md` §4.3, §10.13, SPEC §39).

The voice-agent announces every readiness transition on the `voice:health` pub/sub channel. The
backend turns each announcement into an `INFERENCE_HEALTH_CHANGED` event on every ACTIVE session,
so the instructor console sees the inference stack degrade and recover inside the very log it is
already tailing (`40-realtime-protocol.md` §40.6, row `voice:health`).

The rule this package exists to hold is SPEC §39's closing line — **never silently reset the
simulation**. A health change changes health and nothing else:

* it appends one event per ACTIVE session and writes no other row. `simulation_sessions.state`,
  the incident, the card and the score are not touched, and no use case of `app.application.
  sessions` is called;
* it opens its **own** Unit of Work, so a failure to record a health change can never fail the
  turn or the command that happened to be running;
* no ACTIVE session means no write at all, not an error;
* a malformed announcement is logged and dropped. Redis is a fan-out bus, never a source of truth
  (§40.6): an unreadable message costs the instructor one line in the log, and the next
  `voice:health:{service}` heartbeat re-establishes the state within five seconds anyway.
"""

from __future__ import annotations

from app.application.inference_health.health_changed import (
    AppendInferenceHealthChanged,
    HealthTransition,
)
from app.application.inference_health.ports import InferenceFatalLatch

__all__ = ["AppendInferenceHealthChanged", "HealthTransition", "InferenceFatalLatch"]
