"""The dev/gate transport: `FakeCallTransport` (D13, §2.1).

`SIM_CALL_TRANSPORT=fake` runs the whole voice agent — the pipeline, the detector, the recorder,
the event appends — with no LiveKit server anywhere. The fake itself lives in
`app.application.testing.fakes` next to `FakeClock`, because the same object has to be usable
from a backend unit test, and re-exporting it here is what keeps `voice_agent.wiring` from
importing a testing module by name in the one branch where it needs one.

This module is **not** a production path: D13 is explicit that the fakes are what `make gate`
uses. A deployment selects `SIM_CALL_TRANSPORT=livekit` and gets `LiveKitCallTransport`.
"""

from __future__ import annotations

from app.application.testing.fakes import (
    FakeCallTransport,
    noise_frames,
    silence_frames,
    sine_burst_frames,
)

__all__ = ["FakeCallTransport", "noise_frames", "silence_frames", "sine_burst_frames"]
