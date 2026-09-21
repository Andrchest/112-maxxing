"""Readiness probes (D8, SPEC §37, `openapi.yaml` `getHealthReady`).

`openapi.yaml` names seven components. Three are probed for real here — `postgres`, `redis` and
`livekit` (E11) — and four are not yet probeable at all:

* `llm`, `asr`, `tts`, `vad` — TODO(E18): §40.6 reads them from `voice:health:{service}`, whose
  **writer is the voice-agent process** ("a missing key is `NOT_READY`, never `READY`"). Until the
  agent exists there is no key to read, and a probe that invented `READY` would let a demo session
  start against an inference stack that is not there — the precise failure SPEC §37 exists to
  prevent.

`PlaceholderHealthProbe` is therefore not a stub that pretends: it reports `NOT_READY` with the
reason and the owing epic in `detail`, which is both the honest reading and the documented
behaviour of a missing heartbeat key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.ports.health_probe import ComponentReading
from app.domain.enums import HealthStatus
from app.infrastructure.health.livekit_probe import LiveKitHealthProbe
from app.infrastructure.health.postgres_probe import PROBE_TIMEOUT_S, PostgresHealthProbe
from app.infrastructure.health.redis_probe import RedisHealthProbe

__all__ = [
    "PROBE_TIMEOUT_S",
    "LiveKitHealthProbe",
    "PlaceholderHealthProbe",
    "PostgresHealthProbe",
    "RedisHealthProbe",
]


class PlaceholderHealthProbe:
    """A `HealthProbe` for a component nothing can measure yet — always `NOT_READY`.

    See this package's docstring for why `NOT_READY` is the correct reading rather than a
    placeholder `READY`.
    """

    def __init__(self, component: str, owing_epic: str) -> None:
        self._component = component
        #: The epic that owes the real probe, echoed into `detail` so the UI says who owes it.
        self._owing_epic = owing_epic

    @property
    def component(self) -> str:
        """The `ComponentHealth.component` member this placeholder answers for."""
        return self._component

    async def check(self) -> ComponentReading:
        """`NOT_READY`, with the owing epic as the reason."""
        return ComponentReading(
            component=self._component,
            status=HealthStatus.NOT_READY,
            detail=f"no heartbeat from voice-agent (TODO({self._owing_epic}))",
            checked_at=datetime.now(UTC),
        )
