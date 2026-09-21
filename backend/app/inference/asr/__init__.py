"""ASR adapters for the `ASRProvider` port (HLD `50-voice-pipeline.md` §2.3, `60-inference-ops.md`).

`FakeASR` ships here and is the only provider `make gate` ever loads (D1/D13): scripted text, no
weights, no GPU, no clock. The real providers — `GigaAMProvider` (`v3_e2e_ctc` primary, `v3_ctc`
benchmarked) and the optional `FasterWhisperProvider` — live beside it in `gigaam_provider.py` and
`faster_whisper_provider.py`; they import their heavy packages **lazily**, inside `warm_up()`, so
that `import app.inference.asr` works in a plain dev venv with no extra installed, and they are
selected by `SIM_ASR_PROVIDER` through `voice_agent.providers.build_asr`.

`FakeASR` is imported eagerly because it has no dependency to defer. The other two are not
re-exported here for exactly the opposite reason: re-exporting them would re-introduce the eager
import this module exists to avoid.
"""

from __future__ import annotations

from app.inference.asr.fake_asr import FakeASR

__all__ = ["FakeASR"]
