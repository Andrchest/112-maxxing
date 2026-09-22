"""Operator-facing CLIs that wrap the voice-agent worker's own building blocks (E20-B).

`voice_agent.tools.inject` is the mic-less demo tool (SPEC §46 walk, docs/RUNBOOK.md): it drives
`voice_agent.transport.headless_client.HeadlessTraineeClient` as a trainee whose "microphone" is a
WAV file instead of a sound card. Nothing here is imported by the production agent process
(`voice_agent.main`) — this package exists only for a human (or `docs/DOD_WALK.md`'s E20-C walk)
running a command.
"""

from __future__ import annotations
