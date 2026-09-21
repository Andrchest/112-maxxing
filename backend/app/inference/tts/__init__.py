"""TTS adapters for the `TTSProvider` port (HLD `50-voice-pipeline.md` §2.4, `60-inference-ops.md`).

`FakeTTS` ships here and is the only provider `make gate` ever loads (D1/D13): deterministic PCM,
no weights, no GPU, no network. The real providers — `Qwen3TTS` (GPU default, an httpx client of
the separate `workers/tts_qwen3/` worker process) and `PiperTTS` (the CPU fallback) — live beside
it and import their heavy packages **lazily**, so that `import app.inference.tts` works in a plain
dev venv with no extra installed; they are selected by `SIM_TTS_PROVIDER` through
`voice_agent.providers.build_tts`.

`FakeTTS` is imported eagerly because it has no dependency to defer. The real providers are not
re-exported here for exactly the opposite reason — the same rule `app.inference.asr.__init__`
follows.
"""

from __future__ import annotations

from app.inference.tts.fake_tts import FakeTTS

__all__ = ["FakeTTS"]
