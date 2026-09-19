"""The voice-agent worker process package.

Hosts VAD, ASR and TTS models and runs the turn loop (D9); reuses `app.application` in-process as
a workspace dependency on `sim-backend`. Only `voice_agent.transport` may import the `livekit` SDK;
no module here — or anywhere else in the workspace — may import `openai` or `anthropic` (SPEC §41,
D2).
"""
