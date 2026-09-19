# HLD 50 — Voice pipeline and dialogue turn

Elaborates `docs/SPEC.md` §15–§25 (with §27 latency targets and §44 optimisation rules) under the
decisions **D9** (voice path) and **D10** (dialogue chain) of `docs/hld/00-decisions.md`.
Nothing here re-decides D9/D10; it writes them out at implementation precision.

Reading order for an implementer: this file → `docs/hld/10-domain-model.md` (fact model,
`FactAccessGate` decision table, `AllowedFactsPackage`) → `docs/hld/60-inference-ops.md`
(model profiles, warm-up, readiness, benchmarks).

Naming rule from D0/D1: identifiers, event names and docs are English. Russian appears only in
trainee-facing labels, scenario content, prompt text and caller speech.

Conventions used below:

- Every code block is the **contract**, not a sketch: a later worker copies the signature literally.
- `Target file:` above each block is the exact path the symbol must be created at.
- All ports are `typing.Protocol` and live in `backend/app/application/ports/`; adapters live in
  `backend/app/inference/` or `workers/voice_agent/`, never the other way round (D2).
- Anything this document could not confirm against a primary source is marked **UNVERIFIED** inline
  and must be measured or read from the vendor docs before it is relied on.

---

## 1. Process and module map

| Process | Contains | Talks to |
|:--|:--|:--|
| browser (`frontend`) | LiveKit client SDK, phone widget, WS client | livekit (media), backend (REST + WS) |
| `livekit` | SFU room per call | browser, voice-agent |
| `voice-agent` (`workers/voice_agent/`) | `LiveKitCallTransport`, VAD/ASR/TTS models, `TurnPipeline` | livekit, llama-server, postgres, redis |
| `backend` | FastAPI, use cases, domain, `SimulationRunner` | postgres, redis, livekit-api |
| `llama-server` | Qwen3 GGUF, OpenAI-compatible HTTP | voice-agent (loopback / compose-internal only, §41) |
| `postgres` | authoritative state, `session_events`, transcripts, audio rows | backend, voice-agent |
| `redis` | pub/sub, cancellation, readiness, locks | backend, voice-agent |

Target files created by this document's scope:

```
backend/app/application/ports/call_transport.py      CallTransport, AudioFrame, PlaybackHandle,
                                                     DeliveredAudio, TransportEvent, TransportEventType
backend/app/application/ports/vad.py                 VADProvider, VadFrameResult
backend/app/application/ports/asr.py                 ASRProvider, AsrResult, AsrPartial, AsrWord
backend/app/application/ports/tts.py                 TTSProvider, TtsStream, TtsChunk, TtsVoiceSpec
backend/app/application/ports/llm.py                 LLMClient, ChatMessage, JsonSchemaSpec,
                                                     LlmCompletion, LlmStreamDelta, LlmUsage
backend/app/application/ports/metrics.py             MetricsRecorder, InferenceMetric, InferenceStage
backend/app/application/ports/clock.py               Clock
backend/app/application/voice/turn_detector.py       TurnDetector, TurnDetectorState, VoiceTurnConfig,
                                                     DetectedTurn, PreRollBuffer
backend/app/application/voice/turn_pipeline.py       TurnPipeline, TurnContext, TurnOutcome
backend/app/application/dialogue/interpreter.py      DialogueInterpreter, InterpretedUtterance
backend/app/application/dialogue/generator.py        CallerResponseGenerator, CallerPromptBuilder,
                                                     GeneratedResponse
backend/app/application/dialogue/validator.py        ResponseValidator, ValidationVerdict,
                                                     ValidationFailure, FallbackTemplates
backend/app/domain/dialogue/fact_gate.py             FactAccessGate  (specified in 10-domain-model.md)
workers/voice_agent/transport/livekit_transport.py   LiveKitCallTransport
workers/voice_agent/transport/sip_transport.py       SipCallTransport  (documented TODO stub)
workers/voice_agent/audio/resampler.py               Resampler
workers/voice_agent/recording/recorder.py            SessionRecorder
backend/app/inference/vad/silero.py                  SileroVAD
backend/app/inference/vad/energy.py                  EnergyVAD
backend/app/inference/asr/gigaam.py                  GigaAMProvider
backend/app/inference/asr/faster_whisper.py          FasterWhisperProvider
backend/app/inference/tts/piper.py                   PiperTTS
backend/app/inference/tts/qwen3.py                   Qwen3TTS
backend/app/inference/tts/chatterbox.py              ChatterboxTTS
backend/app/inference/llm/llama_cpp.py               LlamaCppClient
```

Fakes (`FakeASR`, `FakeTTS`, `FakeLLM`, `EnergyVAD`, `FakeCallTransport`) live next to their port
under `backend/app/inference/<kind>/fake.py` and are what `make gate` uses (D13).

---

## 2. Ports

### 2.1 `CallTransport`

Target file: `backend/app/application/ports/call_transport.py`

```python
from __future__ import annotations

import enum
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One block of PCM audio. Our own type: no LiveKit object crosses this boundary (SPEC §15)."""

    pcm: bytes                 # PCM s16le, little-endian, interleaved
    sample_rate: int           # Hz, e.g. 48000 inbound from LiveKit, 16000 after Resampler
    num_channels: int          # 1 after the Resampler; transports may deliver 1 or 2
    samples_per_channel: int   # len(pcm) == samples_per_channel * num_channels * 2
    capture_offset_ms: int     # ms since SESSION_STARTED, from Clock; monotonic, never wall clock


class TransportEventType(enum.StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    RECONNECTED = "RECONNECTED"
    PARTICIPANT_JOINED = "PARTICIPANT_JOINED"
    PARTICIPANT_LEFT = "PARTICIPANT_LEFT"
    TRACK_SUBSCRIBED = "TRACK_SUBSCRIBED"
    TRACK_UNSUBSCRIBED = "TRACK_UNSUBSCRIBED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"


@dataclass(frozen=True, slots=True)
class TransportEvent:
    type: TransportEventType
    call_id: uuid.UUID
    at_offset_ms: int
    participant_identity: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveredAudio:
    """What a cancelled or finished playback actually put on the wire."""

    delivered_audio_ms: int        # audio actually emitted to the transport, playout-adjusted
    total_audio_ms_generated: int  # audio the TTS produced, delivered or not
    frames_delivered: int
    frames_discarded: int
    cancelled: bool                # True when cancel() ended the playback, False on natural end


class PlaybackHandle(Protocol):
    """Handle over one outbound utterance. Returned by CallTransport.play()."""

    @property
    def playback_id(self) -> uuid.UUID: ...

    @property
    def started_offset_ms(self) -> int | None:
        """Offset of the first frame actually handed to the transport; None until then."""

    async def cancel(self) -> DeliveredAudio:
        """Stop playback now, drop queued frames, return what was delivered. Idempotent."""

    async def wait_done(self) -> DeliveredAudio:
        """Await natural end of playback (queue drained)."""

    def is_active(self) -> bool: ...


class CallTransport(Protocol):
    async def connect(self, call_id: uuid.UUID) -> None:
        """Join the media room for this call. Idempotent; raises TransportError on failure."""

    def inbound_audio(self) -> AsyncIterator[AudioFrame]:
        """Trainee microphone frames, in capture order. Ends when the transport disconnects."""

    async def play(self, frames: AsyncIterator[AudioFrame]) -> PlaybackHandle:
        """Start pulling `frames` and emitting them. Returns as soon as playback is scheduled."""

    async def clear_outbound(self) -> None:
        """Discard every frame already queued in the transport's outbound buffer."""

    def events(self) -> AsyncIterator[TransportEvent]: ...

    async def disconnect(self) -> None: ...
```

`LiveKitCallTransport` is the only module allowed to import the `livekit` SDK (D9). Mapping
(verified against `livekit-rtc` `audio_source.py`, September 2026):

| Port element | LiveKit rtc call |
|:--|:--|
| `connect` | `rtc.Room().connect(url, token)` with a backend-minted token |
| `inbound_audio` | `rtc.AudioStream.from_track(track, sample_rate=48000, num_channels=1)` → `AudioFrameEvent.frame` → our `AudioFrame` |
| `play` | `rtc.AudioSource(sample_rate=..., num_channels=1, queue_size_ms=OUTBOUND_QUEUE_MS)` + `await source.capture_frame(frame)` |
| `clear_outbound` | `AudioSource.clear_queue()` |
| queued audio still to play | `AudioSource.queued_duration` (seconds, float) |
| natural end of playback | `await AudioSource.wait_for_playout()` |
| `events` | `Room` event callbacks (`participant_connected`, `track_subscribed`, `reconnecting`, `reconnected`, `disconnected`) pushed into an `asyncio.Queue` |
| `disconnect` | `AudioSource.aclose()` then `Room.disconnect()` |

`SipCallTransport` implements the same Protocol, raises `NotImplementedError("SIP transport is a
documented stub; see SPEC §15")` from `connect`, and exists so that the second implementation is a
file, not a refactor.

### 2.2 `VADProvider`

Target file: `backend/app/application/ports/vad.py`

```python
from dataclasses import dataclass
from typing import Protocol

from app.application.ports.call_transport import AudioFrame


@dataclass(frozen=True, slots=True)
class VadFrameResult:
    speech_probability: float   # 0.0..1.0
    frame_start_ms: int         # session-relative start of the analysed frame
    frame_duration_ms: int


class VADProvider(Protocol):
    @property
    def frame_samples(self) -> int:
        """Fixed window the model requires, in samples at `required_sample_rate`."""

    @property
    def required_sample_rate(self) -> int: ...

    async def warm_up(self) -> None:
        """Run one dummy window so the first real frame is not the first inference (SPEC §37)."""

    def reset(self) -> None:
        """Drop the model's internal recurrent state. Called at the start of every call."""

    async def process(self, frame: AudioFrame) -> VadFrameResult:
        """`frame` must carry exactly `frame_samples` mono samples at `required_sample_rate`."""

    async def close(self) -> None: ...
```

`SileroVAD` (onnxruntime, CPU): `required_sample_rate = 16000`, `frame_samples = 512`
(= 32 ms), which the Silero v5 model fixes; `reset()` clears the recurrent state the model carries
between windows. `EnergyVAD` is a pure-Python RMS-threshold implementation with the same
`frame_samples` so that config and tests are frame-identical; it is the gate's VAD and the fallback
if the onnx model is absent.

### 2.3 `ASRProvider`

Target file: `backend/app/application/ports/asr.py`

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

from app.application.ports.call_transport import AudioFrame


@dataclass(frozen=True, slots=True)
class AsrWord:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None


@dataclass(frozen=True, slots=True)
class AsrResult:
    text: str
    is_final: bool                       # always True for `transcribe`
    start_ms: int                        # session-relative
    end_ms: int
    confidence: float | None
    words: list[AsrWord] = field(default_factory=list)
    provider: str = ""                   # e.g. "gigaam"
    model_version: str = ""              # e.g. "v3_e2e_ctc"
    audio_duration_ms: int = 0
    language: str = "ru"


@dataclass(frozen=True, slots=True)
class AsrPartial:
    text: str
    start_ms: int
    end_ms: int
    stability: float | None              # None when the provider gives no stability signal


class ASRProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def supports_streaming(self) -> bool: ...

    @property
    def required_sample_rate(self) -> int: ...

    async def warm_up(self) -> None: ...

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> AsrResult:
        """Transcribe one finalized turn. `audio` is PCM s16le mono. Always returns is_final=True."""

    def stream(
        self, frames: AsyncIterator[AudioFrame], *, request_id: str
    ) -> AsyncIterator[AsrResult | AsrPartial]:
        """Incremental recognition. Raises UnsupportedOperationError when supports_streaming is False.
        Yields zero or more AsrPartial then exactly one AsrResult with is_final=True."""

    async def close(self) -> None: ...
```

- `GigaAMProvider`: `provider_name = "gigaam"`, `model_version` from the profile
  (`v3_e2e_ctc` primary, `v3_ctc` benchmarked), `required_sample_rate = 16000`, mono. GigaAM v3 is a
  Conformer CTC model for Russian; the e2e variant emits punctuation and normalised text.
  `supports_streaming = False` in the baseline — partials are produced by the pseudo-streaming
  strategy of §4.5 rather than by the model. **UNVERIFIED:** whether the shipped `gigaam` package
  exposes a true streaming API; if it does, `supports_streaming` flips to True and §4.5 uses the
  native stream with no change above the port.
- `FasterWhisperProvider`: optional fallback, `supports_streaming = False`.
- `FakeASR`: returns scripted text, `supports_streaming = True`, used by every gate test.

Downstream code never branches on `provider_name` except when writing telemetry (SPEC §19).

### 2.4 `TTSProvider`

Target file: `backend/app/application/ports/tts.py`

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.application.ports.call_transport import AudioFrame


@dataclass(frozen=True, slots=True)
class TtsVoiceSpec:
    voice_id: str          # CallerProfile.voice_id
    speaking_rate: float   # 1.0 = provider default; CallerProfile.speaking_rate
    pitch: float = 0.0     # semitones; 0.0 = provider default
    language: str = "ru"


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """One cancellable unit of synthesised audio with the text it covers."""

    frame: AudioFrame
    text_offset_start: int   # character offset into the request text this chunk begins at
    text_offset_end: int     # exclusive; the text-alignment metadata D9 requires
    alignment_is_exact: bool # False when the adapter derived offsets word-proportionally
    chunk_index: int
    audio_ms: int


class TtsStream(Protocol):
    @property
    def request_id(self) -> str: ...

    def __aiter__(self) -> AsyncIterator[TtsChunk]: ...

    async def cancel(self) -> None:
        """Stop generation as soon as the current chunk completes. Idempotent."""

    @property
    def text(self) -> str:
        """The exact text handed to the provider — persisted per SPEC §25."""


class TTSProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    @property
    def output_sample_rate(self) -> int: ...

    async def warm_up(self) -> None: ...

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 40,
    ) -> TtsStream:
        """Begin streaming synthesis. Must yield the first chunk without waiting for full synthesis.
        Chunks are at most `max_chunk_ms` of audio so that cancellation is bounded (SPEC §18)."""

    async def close(self) -> None: ...
```

Implementations must never buffer the whole utterance into one WAV before yielding (SPEC §18 last
line). Adapters that can only synthesise sentence-at-a-time still satisfy the port by slicing each
synthesised sentence into `max_chunk_ms` frames as they are produced, and set
`alignment_is_exact = True` at sentence granularity. Adapters with no alignment data at all set
`alignment_is_exact = False` and compute offsets word-proportionally to elapsed audio (D9).

- `PiperTTS` — CPU, onnxruntime, Russian voice models; the lowest-risk profile and the configured
  fallback (D9). **UNVERIFIED:** which Russian Piper voice is selected; a voice id per profile is
  chosen in `60-inference-ops.md` once one is measured.
- `Qwen3TTS` — Qwen3-TTS 0.6B, GPU.
- `ChatterboxTTS` — Chatterbox Multilingual, GPU.
- `FakeTTS` — deterministic silence of a length proportional to the text; exact alignment.

### 2.5 `LLMClient`

Target file: `backend/app/application/ports/llm.py`

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class JsonSchemaSpec:
    """Rendered into llama.cpp's OpenAI-compatible
    `response_format={"type": "json_schema", "json_schema": {...}}`."""

    name: str
    schema: dict[str, Any]
    strict: bool = True


@dataclass(frozen=True, slots=True)
class LlmUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    text: str
    finish_reason: Literal["stop", "length", "cancelled", "error"]
    usage: LlmUsage
    model: str
    request_id: str


@dataclass(frozen=True, slots=True)
class LlmStreamDelta:
    text: str
    index: int
    is_first: bool


class LLMClient(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def n_ctx(self) -> int: ...

    async def warm_up(self) -> None: ...

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: list[str] = (),
        extra_body: dict[str, Any] = field(default_factory=dict),
        timeout_ms: int,
    ) -> LlmCompletion:
        """One non-streaming chat completion. Cancelled by cancelling the awaiting asyncio task,
        which must abort the underlying HTTP request rather than let it run to completion."""

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        request_id: str,
        max_tokens: int,
        temperature: float,
        top_p: float = 0.95,
        response_format: JsonSchemaSpec | None = None,
        stop: list[str] = (),
        extra_body: dict[str, Any] = field(default_factory=dict),
        timeout_ms: int,
    ) -> AsyncIterator[LlmStreamDelta]:
        """Token stream. Closing the iterator (`aclose`) must cancel generation server-side."""

    async def cancel(self, request_id: str) -> None:
        """Best-effort out-of-band cancellation for a request issued from another task."""

    async def close(self) -> None: ...
```

`LlamaCppClient` sends `extra_body = {"chat_template_kwargs": {"enable_thinking": false}}` and
prefixes the last user message with `/no_think` (D10) so that Qwen3 thinking is off in both the
template-aware and template-unaware server builds. Its `base_url` is validated at config load to be
loopback or a compose-internal hostname (SPEC §41); any other value is a start-up error.

### 2.6 `MetricsRecorder` and `InferenceMetric`

Target file: `backend/app/application/ports/metrics.py`

```python
import enum
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class InferenceStage(enum.StrEnum):
    ASR = "ASR"
    LLM_INTERPRET = "LLM_INTERPRET"
    LLM_GENERATE = "LLM_GENERATE"
    TTS = "TTS"


@dataclass(frozen=True, slots=True)
class InferenceMetric:
    """Every SPEC §27 field. Persisted to `inference_metrics`; column names are the field names."""

    id: uuid.UUID
    session_id: uuid.UUID
    turn_id: uuid.UUID | None
    request_id: str
    stage: InferenceStage
    provider: str
    model_version: str
    input_tokens: int | None
    input_audio_ms: int | None
    output_tokens: int | None
    output_audio_ms: int | None
    started_at: datetime
    first_output_at: datetime | None
    finished_at: datetime | None
    ttft_ms: int | None
    total_latency_ms: int | None
    tokens_per_second: float | None
    realtime_factor: float | None
    gpu_memory_used_mb: int | None
    fallback_count: int
    retry_count: int
    status: str            # "OK" | "TIMEOUT" | "ERROR" | "CANCELLED"
    error_kind: str | None


class MetricsRecorder(Protocol):
    async def record(self, metric: InferenceMetric) -> None: ...

    async def record_turn_latency(
        self, session_id: uuid.UUID, turn_id: uuid.UUID, speech_end_to_first_audio_ms: int
    ) -> None:
        """The SPEC §27 critical product metric, stored on the turn row, not on a stage row."""
```

### 2.7 `Clock`

Target file: `backend/app/application/ports/clock.py`

```python
from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime:
        """Timezone-aware UTC wall clock. Used only for `timestamp_utc` on persisted records."""

    def monotonic_ms(self) -> int:
        """Monotonic milliseconds from an arbitrary origin. Never wall clock."""

    def session_offset_ms(self) -> int:
        """monotonic ms since SESSION_STARTED for the session this Clock is bound to (D5)."""
```

`SystemClock` (infrastructure) wraps `datetime.now(UTC)` and `time.monotonic_ns()`.
`FakeClock` (tests) is advanced explicitly. Domain code receives a `Clock`; it never calls
`time.time()` (D2).

---

## 3. Stage classes

The pipeline order is fixed by D9 and SPEC §16 and is never reordered or collapsed:

```
CallTransport.inbound_audio -> Resampler -> VADProvider -> TurnDetector -> ASRProvider
  -> DialogueInterpreter -> FactAccessGate -> CallerResponseGenerator -> ResponseValidator
  -> TTSProvider.stream -> CallTransport.play
```

### 3.1 `Resampler`

Target file: `workers/voice_agent/audio/resampler.py`.
Input `AudioFrame` at the transport rate (48 kHz from LiveKit), output `AudioFrame` at 16 kHz mono,
peak-normalised to a configured target with a limiter so a loud trainee cannot clip VAD/ASR input.
It re-blocks the stream to exactly `VADProvider.frame_samples` samples per output frame, carrying a
remainder buffer across inputs, and preserves `capture_offset_ms` of the first contained sample.
Pure and synchronous; no model, no I/O. Emits no events.

### 3.2 `TurnDetector`

Target file: `backend/app/application/voice/turn_detector.py`.
**Responsibility:** decide, from `VadFrameResult` values only, when the trainee started and stopped
speaking, and whether a barge-in has occurred. It never sees text.
**Input:** a stream of `(AudioFrame, VadFrameResult)` plus a `playback_active: bool` flag the
`TurnPipeline` sets while a `PlaybackHandle` is live.
**Output:** `DetectedTurn {turn_id, audio: bytes, start_ms, end_ms, is_barge_in, pre_roll_ms}` and,
before that, the two boundary signals.
**Events:** `USER_SPEECH_STARTED` at the IDLE/PRE_SPEECH → IN_SPEECH transition (payload
`{turn_id, start_ms, was_during_playback}`); `USER_SPEECH_ENDED` at ENDPOINTING → IDLE (payload
`{turn_id, start_ms, end_ms, duration_ms, end_reason}`, `end_reason ∈ {ENDPOINT_SILENCE,
MAX_TURN_MS, TRANSPORT_CLOSED}`). Full algorithm in §4.

### 3.3 `DialogueInterpreter`

Target file: `backend/app/application/dialogue/interpreter.py`.
**Responsibility:** turn one operator utterance into the constrained structure of SPEC §20. It is the
first LLM call of the turn and it never sees fact **values** — only the catalog (D10).
**Input:** `AsrResult.text`, the last 4–6 turns, and the fact catalog
(`fact_id`, `label_ru`, `aliases_ru`, `categories`).
**Output:** `InterpretedUtterance` (§5.1).
**Events:** `DIALOGUE_INTERPRETED` (payload `{turn_id, speech_act, requested_facts,
operator_assertions, confirmation_targets, semantic_confidence, repair_used}`) on success;
`MODEL_FALLBACK_USED {turn_id, stage: "INTERPRETER", reason}` when both the first attempt and the
repair retry fail schema validation; `MODEL_ERROR {turn_id, stage: "INTERPRETER", error_kind}` when
the LLM call itself fails (timeout, transport, HTTP 5xx).

### 3.4 `FactAccessGate`

Target file: `backend/app/domain/dialogue/fact_gate.py`.
**Specified in `docs/hld/10-domain-model.md`** — its decision table (knowledge state × disclosure
policy × `available_after` × explicitness → released / withheld / unavailable / not_yet) is owned
there and is **not** restated or altered here. This document only fixes its place in the pipeline and
its I/O shape as D10 states them:
**Input:** `InterpretedUtterance`, `ScenarioVersion`, current `WorldTruth`, current `CallerBelief`,
previously revealed fact ids, current simulation time/state.
**Output:** `AllowedFactsPackage {allowed[], unavailable[], withheld_count, metadata}` — caller
values only; a world value can never appear in it.
**Events:** `FACT_GATE_EVALUATED {turn_id, requested, allowed, unavailable, withheld_count}`.
It is a pure function: no clock, no I/O, no LLM. Collapsing it into a prompt is forbidden
(SPEC §16, §44).

### 3.5 `CallerResponseGenerator`

Target file: `backend/app/application/dialogue/generator.py`.
**Responsibility:** produce Russian caller wording from the `AllowedFactsPackage` and persona only.
`CallerPromptBuilder` accepts `AllowedFactsPackage` + `CallerProfile` + current emotion + recent
turns + the current utterance, and has no parameter through which a `WorldTruth` or
`ScenarioVersion` could arrive (D3).
**Input/Output:** `(AllowedFactsPackage, CallerProfile, EmotionState, list[TurnRecord], str)` →
`GeneratedResponse {utterance, attempt, usage, request_id}`.
**Events:** `CALLER_RESPONSE_PLANNED {turn_id, allowed_fact_ids, withheld_count, emotion}` emitted
*before* the generation call, from gate output alone — so the plan is auditable even if generation
fails; `CALLER_RESPONSE_GENERATED {turn_id, text, attempt, prompt_tokens, completion_tokens,
validated}` after the response has passed `ResponseValidator`;
`MODEL_ERROR {turn_id, stage: "GENERATOR", error_kind}` on call failure.

### 3.6 `ResponseValidator`

Target file: `backend/app/application/dialogue/validator.py`.
**Responsibility:** the deterministic SPEC §24 gate between the model and the trainee's ear.
**Input:** the raw model output string, the `AllowedFactsPackage`, the already-revealed values, the
operator's recent utterances, the persona whitelist, and the full set of scenario values **not** in
the package (the validator is code and may see them; the LLM never does — D10).
**Output:** `ValidationVerdict {ok, failures: list[ValidationFailure], normalized_text}`.
**Events:** it emits none itself; `CallerResponseGenerator` emits
`MODEL_FALLBACK_USED {turn_id, stage: "VALIDATOR", reason, failure_codes}` when the single
regeneration also fails and the deterministic template is used. Algorithms in §7.

### 3.7 `TurnPipeline`

Target file: `backend/app/application/voice/turn_pipeline.py`.
**Responsibility:** own the per-call asyncio task graph, wire the stages, hold the single
`PlaybackHandle`, and be the only place that appends voice `SessionEvents`.
It runs three long-lived tasks per call:

1. `_ingest` — `inbound_audio()` → `Resampler` → `VADProvider` → `TurnDetector`, plus writing the
   trainee recording (§9).
2. `_respond` — consumes `DetectedTurn`s from a queue of depth 1 (a second finalized turn while one
   is in flight cancels the in-flight response as a barge-in) and runs
   ASR → interpret → gate → generate → validate → TTS → play.
3. `_control` — `events()` from the transport, and the Redis subscriptions
   `voice:cancel:{session_id}` (hang-up / abort) and `voice:join`.

**Events emitted by `TurnPipeline` itself:** `ASR_PARTIAL`, `ASR_FINAL`, `CALLER_TTS_STARTED`,
`CALLER_TTS_ENDED`, `CALLER_UTTERANCE_INTERRUPTED`, `FACTS_DELIVERED`, `TRANSPORT_DISCONNECTED`,
`TRANSPORT_RECONNECTED`, `CALL_ENDED`. It re-emits the stage events of §3.2–§3.6 through the same
append path so that `seq_no` allocation stays under the D5 row lock.

Per-turn event order for a normal turn (no barge-in):

```
USER_SPEECH_STARTED
ASR_PARTIAL            (0..n, only when partials are enabled and produced)
USER_SPEECH_ENDED
ASR_FINAL
DIALOGUE_INTERPRETED
FACT_GATE_EVALUATED
CALLER_RESPONSE_PLANNED
CALLER_RESPONSE_GENERATED
CALLER_TTS_STARTED
CALLER_TTS_ENDED
FACTS_DELIVERED
```

`FACTS_DELIVERED {turn_id, fact_ids}` is emitted **only** after `CALLER_TTS_ENDED` of an
uninterrupted playback (D10). An interrupted response reveals nothing and emits no
`FACTS_DELIVERED`, so rewording caller text cannot move a score (SPEC §42 test 10).

---

## 4. `TurnDetector` algorithm

### 4.1 `VoiceTurnConfig`

Target file: `backend/app/application/voice/turn_detector.py`; values come from the active model
profile and `.env`, never from literals in code (D9).

| Key | Type | Default | Valid range | Meaning |
|:--|:--|:--|:--|:--|
| `speech_start_threshold` | float | 0.55 | 0.30–0.90 | VAD probability at or above which a frame counts as speech |
| `speech_end_threshold` | float | 0.35 | 0.10–`speech_start_threshold` | probability below which a frame counts as silence (hysteresis) |
| `speech_start_min_ms` | int | 96 | 32–400, multiple of `vad_frame_ms` | consecutive speech needed to leave PRE_SPEECH |
| `endpoint_silence_ms` | int | 300 | 250–350 (SPEC §17 initial target); hard bound 150–1500 | trailing silence that finalizes a turn |
| `pre_roll_ms` | int | 300 | 100–1000 | audio kept before speech onset so word beginnings survive |
| `barge_in_min_speech_ms` | int | 120 | 60–400, multiple of `vad_frame_ms` | sustained speech during playback before a barge-in fires |
| `max_turn_ms` | int | 30000 | 5000–120000 | hard cap; forces `end_reason = MAX_TURN_MS` |
| `min_turn_ms` | int | 200 | 0–2000 | turns shorter than this are discarded as noise, no ASR |
| `vad_frame_ms` | int | 32 | fixed by `VADProvider.frame_samples` | analysis frame length |
| `outbound_queue_ms` | int | 200 | 40–500 | transport outbound buffer depth (`queue_size_ms`) |
| `tts_chunk_ms` | int | 40 | 10–60 | `max_chunk_ms` handed to `TTSProvider.stream` |
| `partial_asr_enabled` | bool | true | — | whether `ASR_PARTIAL` is produced at all (also gated per session by `SessionPolicy`, D6) |
| `partial_interval_ms` | int | 500 | 200–2000 | pseudo-streaming partial cadence (§4.5) |

Validation at load: `speech_end_threshold <= speech_start_threshold`;
`speech_start_min_ms`, `barge_in_min_speech_ms` and `endpoint_silence_ms` are integer multiples of
`vad_frame_ms` (rounded up at load with a warning if not); `min_turn_ms < max_turn_ms`;
`tts_chunk_ms <= outbound_queue_ms`.

### 4.2 Pre-roll ring buffer

`PreRollBuffer` is a fixed-capacity deque of resampled `AudioFrame`s holding
`ceil(pre_roll_ms / vad_frame_ms)` frames (default 300/32 → 10 frames = 320 ms ≥ 300 ms). Every
frame that reaches the `TurnDetector` is pushed; the oldest is evicted. When the detector enters
IN_SPEECH, the whole buffer is copied to the front of the turn's audio accumulator before the
current frame, so the recognised audio begins `pre_roll_ms` before the VAD trigger. The buffer is
never cleared during IN_SPEECH (its contents are already in the accumulator) and is cleared on
`reset()`.

### 4.3 States

```
IDLE        no speech; frames go only to the pre-roll buffer
PRE_SPEECH  speech-probability above start threshold, not yet sustained
IN_SPEECH   turn is open, frames accumulate
ENDPOINTING trailing silence is being counted; frames still accumulate
```

The barge-in branch is not a fourth state but a flag carried through PRE_SPEECH/IN_SPEECH: when the
transition IDLE → PRE_SPEECH happens while `playback_active` is true, the detector sets
`was_during_playback = True` for that turn and applies `barge_in_min_speech_ms` instead of
`speech_start_min_ms` as the sustain threshold, because a barge-in must be confirmed faster than a
cold turn start (SPEC §18 step 1).

### 4.4 Transition table

Per frame `f` with probability `p`, `speech = p >= speech_start_threshold`,
`silence = p < speech_end_threshold`:

| From | Condition | To | Side effect |
|:--|:--|:--|:--|
| IDLE | `speech` | PRE_SPEECH | `speech_run_ms = vad_frame_ms`; `was_during_playback = playback_active`; `sustain_ms = barge_in_min_speech_ms if playback_active else speech_start_min_ms` |
| IDLE | else | IDLE | push `f` to `PreRollBuffer` |
| PRE_SPEECH | `speech` and `speech_run_ms + vad_frame_ms >= sustain_ms` | IN_SPEECH | copy `PreRollBuffer` then `f` into the accumulator; `turn_id = uuid4()`; `start_ms = f.capture_offset_ms - pre_roll_ms` (clamped at 0); emit `USER_SPEECH_STARTED`; if `was_during_playback` run the barge-in procedure of §6 |
| PRE_SPEECH | `speech` | PRE_SPEECH | `speech_run_ms += vad_frame_ms`; push `f` to `PreRollBuffer` |
| PRE_SPEECH | not `speech` | IDLE | `speech_run_ms = 0`; push `f` to `PreRollBuffer` |
| IN_SPEECH | `silence` | ENDPOINTING | `silence_run_ms = vad_frame_ms`; accumulate `f` |
| IN_SPEECH | `turn_ms >= max_turn_ms` | IDLE | finalize with `end_reason = MAX_TURN_MS` |
| IN_SPEECH | else | IN_SPEECH | accumulate `f` |
| ENDPOINTING | `speech` | IN_SPEECH | `silence_run_ms = 0`; accumulate `f` |
| ENDPOINTING | `silence` and `silence_run_ms + vad_frame_ms >= endpoint_silence_ms` | IDLE | finalize with `end_reason = ENDPOINT_SILENCE` |
| ENDPOINTING | `silence` | ENDPOINTING | `silence_run_ms += vad_frame_ms`; accumulate `f` |
| any | transport closed | IDLE | finalize with `end_reason = TRANSPORT_CLOSED` if a turn is open |

Finalization: trim the trailing `endpoint_silence_ms` of accumulated audio down to a kept
`trailing_pad_ms = 100` so ASR keeps the final consonant but not the whole pause; set
`end_ms = start_ms + kept_duration_ms`; emit `USER_SPEECH_ENDED`; if
`end_ms - start_ms - pre_roll_ms < min_turn_ms` discard the turn (no ASR, no response — the
`USER_SPEECH_*` pair is still logged, with `end_reason = ENDPOINT_SILENCE` and a payload flag
`discarded_short: true`); otherwise push the `DetectedTurn` to the respond queue.

Probabilities between the two thresholds leave the state unchanged and extend neither run counter —
that is the hysteresis band and it is what keeps breath noise from re-opening a closing turn.

### 4.5 Partial ASR

`ASR_PARTIAL {turn_id, text, start_ms, end_ms, stability}` is produced while IN_SPEECH/ENDPOINTING,
subject to `partial_asr_enabled` **and** the session's `SessionPolicy.show_asr_partials` (D6) —
assessment modes can switch partials off without touching the pipeline.

- If `ASRProvider.supports_streaming` is true, the accumulated frames are forwarded to
  `ASRProvider.stream()` and every `AsrPartial` it yields becomes one `ASR_PARTIAL`.
- Otherwise (GigaAM baseline) the pipeline pseudo-streams: every `partial_interval_ms` of accumulated
  audio it calls `transcribe()` on the accumulation-so-far in a **separate task** with a request id
  `{turn_id}:p{n}`, and emits the result as `ASR_PARTIAL` with `stability = None`. A pending partial
  task is cancelled the moment `USER_SPEECH_ENDED` fires; its result is discarded, never merged.
  A partial never feeds the interpreter, never reaches the incident card (SPEC §9, §42 test 4) and
  never counts toward latency: the response starts only from the final turn (SPEC §17).

`ASR_FINAL {turn_id, text, start_ms, end_ms, confidence, provider, model_version,
audio_segment_id, transcript_segment_id}` is emitted once per surviving turn, from the single
`transcribe()` call over the finalized audio.

---

## 5. Prompts and schemas

### 5.1 Interpreter

Schema (SPEC §20, D10). Target file: `backend/app/application/dialogue/interpreter.py`, exported as
`INTERPRETER_JSON_SCHEMA` and handed to `LLMClient.complete(response_format=JsonSchemaSpec(
name="operator_utterance_interpretation", schema=INTERPRETER_JSON_SCHEMA, strict=True))`.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["speech_act", "requested_facts", "operator_assertions",
               "confirmation_targets", "semantic_confidence"],
  "properties": {
    "speech_act": {
      "type": "string",
      "enum": ["QUESTION", "STATEMENT", "CONFIRMATION", "INSTRUCTION",
               "GREETING", "CLOSING", "OTHER", "UNINTELLIGIBLE"]
    },
    "requested_facts": {
      "type": "array", "maxItems": 8,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["fact_id", "explicit"],
        "properties": {
          "fact_id": {"type": "string"},
          "explicit": {"type": "boolean"}
        }
      }
    },
    "operator_assertions": {
      "type": "array", "maxItems": 8,
      "items": {
        "type": "object", "additionalProperties": false,
        "required": ["fact_id", "asserted_value"],
        "properties": {
          "fact_id": {"type": "string"},
          "asserted_value": {"type": "string"}
        }
      }
    },
    "confirmation_targets": {
      "type": "array", "maxItems": 8, "items": {"type": "string"}
    },
    "semantic_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
  }
}
```

Mirrored by a Pydantic v2 model `InterpretedUtterance` with `model_config =
ConfigDict(extra="forbid")`. Post-schema validation, enforced in code, not in the prompt:
every `fact_id` in `requested_facts`, `operator_assertions` and `confirmation_targets` must be a
member of the catalog handed to this call; unknown ids are a validation failure, never dropped
silently (SPEC §20 last line). `explicit = true` only when the operator named the fact or one of its
`aliases_ru`; a broad category question such as «что случилось?» yields `explicit=false` (D10).

System prompt (`INTERPRETER_SYSTEM_PROMPT_RU`, Russian, verbatim):

```
Ты — анализатор реплик оператора службы 112. Ты НЕ отвечаешь оператору и НЕ ведёшь диалог.
Твоя единственная задача — превратить реплику оператора в строгий JSON по заданной схеме.

Правила:
1. Возвращай только JSON. Никакого текста до или после, никаких пояснений.
2. Поле speech_act: QUESTION — оператор спрашивает; STATEMENT — сообщает или инструктирует
   без вопроса; CONFIRMATION — переспрашивает или уточняет уже названное; INSTRUCTION — даёт
   указание («выйдите из здания»); GREETING — приветствие; CLOSING — завершение разговора;
   OTHER — иное; UNINTELLIGIBLE — реплика непонятна или пуста.
3. В requested_facts указывай ТОЛЬКО fact_id из КАТАЛОГА ФАКТОВ ниже. Никаких новых
   идентификаторов не придумывай. Если подходящего факта в каталоге нет — не добавляй ничего.
4. Для каждого запрошенного факта укажи explicit:
   true  — оператор назвал этот факт прямо, своим именем или одним из его синонимов;
   false — факт подразумевается общим вопросом (например «что случилось?», «что там у вас?»).
5. operator_assertions — утверждения оператора о значении факта («значит, это дом 27»):
   fact_id из каталога и asserted_value строкой, как её произнёс оператор.
6. confirmation_targets — fact_id, которые оператор переспрашивает.
7. semantic_confidence — твоя уверенность в разборе, число от 0 до 1.
8. Не угадывай. Пустой список лучше выдуманного значения.

КАТАЛОГ ФАКТОВ:
{fact_catalog}
```

`{fact_catalog}` rendering — one line per fact, **values never appear**:

```
- <fact_id> | <label_ru> | синонимы: <alias_1>, <alias_2>, … | категории: <cat_1>, <cat_2>
```

User message:

```
ПОСЛЕДНИЕ РЕПЛИКИ:
{recent_turns}

РЕПЛИКА ОПЕРАТОРА:
{operator_utterance}
```

`{recent_turns}` is the same 4–6 turn window as §5.3, rendered `ОПЕРАТОР: …` / `ЗВОНЯЩИЙ: …`.

Call parameters: `max_tokens = 200`, `temperature = 0.0`, `top_p = 1.0`, `timeout_ms = 2500`.

**Repair prompt** (`INTERPRETER_REPAIR_PROMPT_RU`) — one retry only (SPEC §20, §39). The failed raw
output and the validator's message are appended as an extra user message; the system prompt is
unchanged:

```
Твой предыдущий ответ не прошёл проверку схемы.

ТВОЙ ОТВЕТ:
{previous_raw_output}

ОШИБКА:
{validation_error}

Верни исправленный JSON, строго по схеме. Только JSON, без пояснений.
Не добавляй идентификаторы, которых нет в КАТАЛОГЕ ФАКТОВ.
```

**Fallback** when the repair also fails, or the LLM call errors or times out: the interpreter returns
`InterpretedUtterance(speech_act="UNINTELLIGIBLE", requested_facts=[], operator_assertions=[],
confirmation_targets=[], semantic_confidence=0.0)` and the pipeline emits `MODEL_FALLBACK_USED`.
The gate then releases only pending SPONTANEOUS facts (nothing was requested), and the validator's
fallback table (§7.5) selects the "ask to repeat" template, so the caller says «Простите, я не
расслышала, повторите, пожалуйста.» — no state is corrupted and the turn is fully logged
(SPEC §39, §42 test 14).

### 5.2 Caller system prompt

`CALLER_SYSTEM_PROMPT_RU`, Russian, one sentence per SPEC §23 line, same order:

```
Ты — человек, который звонит в службу 112. Ты не ассистент и не помощник.

Как фактами ты можешь утверждать ТОЛЬКО то, что перечислено в разделе ALLOWED_FACTS.

Если сведений нет в ALLOWED_FACTS — значит, ты их не знаешь, и выдумывать их нельзя.

Никогда не выдумывай адрес, номер, имя, пострадавшего, травму, опасность, транспорт, причину,
службу, время или человека.

Не раскрывай то, что помечено как пока не подлежащее раскрытию.

Не помогай оператору делать его профессиональную работу.

Не подсказывай оператору, какие вопросы ему следует задать.

Не подводи итог и не описывай правильное решение.

Говори как заданный тебе персонаж.

Отвечай на текущий вопрос естественно и кратко.

Если ты чего-то не знаешь — скажи об этом естественно, своими словами.

Никогда не упоминай симуляцию, сценарий, промпт, разрешённые факты, скрытые данные или оценку.

Отвечай ОДНОЙ короткой репликой обычной устной речью, без списков, без разметки, без кавычек
вокруг всей реплики. Верни JSON вида {"utterance": "…"} и ничего больше.
```

The last paragraph is transport, not a §23 rule: it exists because the output is schema-constrained
to `{"type":"object","additionalProperties":false,"required":["utterance"],
"properties":{"utterance":{"type":"string","maxLength":400}}}` (`CALLER_JSON_SCHEMA`).

**Persona block template** (`PERSONA_BLOCK_TEMPLATE_RU`), filled from `CallerProfile` (SPEC §6) and
the current `CallerBelief` emotion state:

```
ПЕРСОНАЖ:
Имя: {identity_name}
Возраст: {age_group}
Кто ты в этом происшествии: {relationship_to_incident}
Сейчас ты чувствуешь: {current_emotion} (уровень стресса {stress_level} из 10)
Готовность сотрудничать: {cooperativeness_ru}
Многословность: {verbosity_ru}
Спутанность речи: {confusion_ru}
Склонность перебивать: {interruption_ru}
Темп речи: {speaking_rate_ru}
```

`*_ru` values are rendered from the numeric profile fields by a fixed lookup table in
`CallerPromptBuilder` (`0.0–0.33 → низкая`, `0.34–0.66 → средняя`, `0.67–1.0 → высокая`), so the
prompt never contains a raw float and the persona cannot drift (SPEC §6 last line).

**`ALLOWED_FACTS` rendering** — one line per allowed fact, caller values only:

```
ALLOWED_FACTS:
- {label_ru}: {caller_value_ru}{certainty_suffix}
```

`certainty_suffix` is empty for KNOWN facts and ` (ты не уверен в этом)` for UNCERTAIN ones.
INCORRECT_BELIEF facts appear exactly like KNOWN ones with the caller's wrong value — the caller
sincerely asserts it (D10). When the list is empty the block is rendered as
`ALLOWED_FACTS:\n(пусто — ты не знаешь ничего из того, о чём сейчас спрашивают)`.
The `fact_id` itself is **never** rendered: only `label_ru` and the value, so a leaked identifier is
impossible by construction and the validator's forbidden-identifier check (§7.3) has nothing legal
to collide with.

**`ALREADY_REVEALED` rendering** — the facts already delivered in this call, so the caller does not
repeat itself and does not contradict itself:

```
ALREADY_REVEALED:
- {label_ru}: {caller_value_ru}
```

Empty case: `ALREADY_REVEALED:\n(пока ничего)`.

**Turn window policy (4–6 turns, SPEC §22):** a turn is one operator utterance plus the caller reply
that followed it. `CallerPromptBuilder` takes the last 6 turns, then drops the oldest turns while the
rendered window exceeds `turn_window_token_budget` (see §5.3), but never drops below 4 turns; if 4
turns still exceed the budget, the oldest of the four has its caller reply truncated to its first
sentence. The full transcript stays in PostgreSQL and is never sent (SPEC §22).

User message layout, in this exact order:

```
{persona_block}

{allowed_facts_block}

{already_revealed_block}

ПОСЛЕДНИЕ РЕПЛИКИ:
{recent_turns}

ОПЕРАТОР ГОВОРИТ: {operator_utterance}
```

Call parameters: `max_tokens = 80` (SPEC §22), `temperature = 0.7`, `top_p = 0.9`,
`timeout_ms = 3000`, `response_format = CALLER_JSON_SCHEMA`, and the D10 thinking-off pair
(`/no_think` prefix on the last user message + `chat_template_kwargs.enable_thinking=false`).

### 5.3 Token budget for `n_ctx = 4096`

Budget accounting is per generation call; the generator refuses to build a prompt that exceeds
`prompt_token_budget` and sheds turns until it fits.

| Segment | Budget (tokens) | Note |
|:--|:--|:--|
| `CALLER_SYSTEM_PROMPT_RU` | 420 | fixed text; measured once at start-up and asserted ≤ budget |
| persona block | 160 | fixed shape, 9 short lines |
| `ALLOWED_FACTS` | 300 | ~12 facts × ~25 tokens; gate output is capped at 12 released facts per turn |
| `ALREADY_REVEALED` | 300 | same shape; truncated oldest-first if exceeded |
| turn window (`turn_window_token_budget`) | 1200 | 4–6 turns of Russian speech |
| current operator utterance | 200 | ASR text of one turn |
| JSON schema / template overhead | 120 | grammar preamble and chat-template tokens |
| **prompt total (`prompt_token_budget`)** | **2700** | hard refusal above this |
| generation (`max_tokens`) | 80 | SPEC §22 |
| **headroom** | **1316** | absorbs tokenizer variance and a long ASR turn |

The interpreter call uses the same `n_ctx` but a different split: system + catalog ≤ 1800
(`fact_catalog` is capped at 60 facts × ~22 tokens), window 1200, utterance 200, generation 200.
A scenario whose catalog exceeds the cap fails **scenario validation**, not runtime (D4) — the check
belongs in `10-domain-model.md` and is named here only so the two documents agree.

---

## 6. Barge-in

### 6.1 Procedure

Triggered by the PRE_SPEECH → IN_SPEECH transition with `was_during_playback = True` (§4.4). In this
exact order (SPEC §18 steps 1–7):

1. **Confirm** — already done: the transition required `barge_in_min_speech_ms` of sustained speech.
2. **Cancel generation** — `await tts_stream.cancel()` and, if the LLM generation for this playback is
   still streaming, `await llm_stream.aclose()`. Both are non-blocking beyond the current chunk.
3. **Clear the queue** — `await transport.clear_outbound()` (LiveKit `AudioSource.clear_queue()`).
4. **Stop playback** — `delivered = await playback_handle.cancel()`.
5. **Emit** `CALLER_UTTERANCE_INTERRUPTED`.
6. **Preserve** `delivered_text` / `delivered_audio_ms` (§6.3) and persist (§6.4).
7. **Process the trainee turn normally** — the detector is already IN_SPEECH; nothing special
   happens downstream, and the interrupted facts are *not* marked revealed.

Steps 2–4 run concurrently under `asyncio.gather`; step 3 is what actually stops sound, so it is
issued first inside the gather and never waits on step 2.

### 6.2 Timing budget: speech onset → audio cutoff

Target: **< 250 ms** (SPEC §18). Onset is the first sample of trainee speech; cutoff is the last
sample the trainee hears.

| # | Contribution | ms | Why |
|:--|:--|--:|:--|
| 1 | VAD frame quantisation | ≤ 32 | onset can fall just after a frame boundary; Silero v5 window is 512 samples @ 16 kHz |
| 2 | Sustain confirmation `barge_in_min_speech_ms` | 120 | SPEC §18 step 1; 4 frames minimum below which breath noise cuts the caller off |
| 3 | Detector + task hand-off | ≤ 5 | in-process, one `asyncio` queue put and a coroutine step |
| 4 | `clear_outbound()` round trip | ≤ 5 | `AudioSource.clear_queue()` is a local FFI call, no network |
| 5 | Residual audio already past the queue | ≤ 40 | one `tts_chunk_ms` frame may already be inside the LiveKit encoder |
| 6 | Network + jitter buffer to the browser | ≤ 40 | loopback/LAN WebRTC; the browser's own jitter buffer dominates. **UNVERIFIED** — measured by `benchmark_e2e.py` |
| | **Total** | **≤ 242** | margin 8 ms at defaults |

Two knobs keep this inside budget and are the only ones allowed to move:

- `outbound_queue_ms` (default 200) does **not** appear in the budget because `clear_outbound()`
  discards it. It appears only if the transport cannot clear: a transport whose `clear_outbound()` is
  a no-op would add its full queue depth, which is why `LiveKitCallTransport` is required to map it to
  `clear_queue()` and why `FakeCallTransport` implements it truthfully for SPEC §42 test 12.
- `barge_in_min_speech_ms` is the dominant term. Lowering it below 60 ms trades false barge-ins for
  latency and is rejected by config validation.

If the measured budget is exceeded on real hardware, the permitted responses are: lower
`tts_chunk_ms` toward 10, lower `outbound_queue_ms` toward 40, lower `barge_in_min_speech_ms` toward
60. Removing the sustain confirmation, skipping `CALLER_UTTERANCE_INTERRUPTED`, or letting the
caller finish are **not** permitted (SPEC §18, §44).

### 6.3 Computing `delivered_text` and `delivered_audio_ms`

`delivered_audio_ms` comes from the transport, not from the TTS: it is the sum of `audio_ms` of every
chunk the `PlaybackHandle` actually handed to `AudioSource.capture_frame`, **minus** the audio still
queued at cancel time, read from `AudioSource.queued_duration` immediately before `clear_queue()`:

```
delivered_audio_ms = sum(chunk.audio_ms for chunk in captured_chunks)
                     - round(queued_duration_at_cancel * 1000)
```

clamped to `[0, total_audio_ms_generated]`. `total_audio_ms_generated` is the sum over every chunk
the TTS produced, including chunks generated but never captured.

`delivered_text` is derived from chunk alignment metadata (D9):

1. Find the last chunk `c` whose cumulative captured audio is ≤ `delivered_audio_ms`.
2. If `c.alignment_is_exact`, `delivered_text = planned_text[: c.text_offset_end]`.
3. Otherwise (word-proportional fallback) let `r = delivered_audio_ms / total_audio_ms_generated`,
   split `planned_text` into words, take the first `round(r * len(words))` words, and set
   `alignment_is_exact = false` in the payload so a reader knows the boundary is approximate.
4. Trailing partial-word characters are dropped; the result is right-stripped.

`CALLER_UTTERANCE_INTERRUPTED` payload, exactly:

```json
{
  "turn_id": "<uuid of the interrupted caller turn>",
  "interrupting_turn_id": "<uuid of the trainee turn that caused it>",
  "planned_text": "<full validated text sent to TTS>",
  "delivered_text": "<prefix actually heard>",
  "delivered_audio_ms": 0,
  "total_audio_ms_generated": 0,
  "alignment_is_exact": true,
  "fact_ids_not_revealed": ["<fact_id>", "…"],
  "cutoff_latency_ms": 0
}
```

`cutoff_latency_ms` is `clear_outbound()` completion offset minus `USER_SPEECH_STARTED` offset — the
measured value of §6.2, recorded every time so the target is monitored and not assumed.

### 6.4 What is persisted on a barge-in

| Store | Row | Content |
|:--|:--|:--|
| `session_events` | one | `CALLER_UTTERANCE_INTERRUPTED` with the payload above; immutable (D5) |
| `session_events` | one | `CALLER_TTS_ENDED` is **not** emitted — an interrupted playback has no natural end |
| `session_events` | none | no `FACTS_DELIVERED`: the facts stay unrevealed and may be asked again (D10) |
| `transcript_segments` | one | speaker `CALLER`, `text = delivered_text`, `is_final = true`, `start_ms`, `end_ms = start_ms + delivered_audio_ms`, `audio_segment_id` of the caller segment |
| `audio_segments` | one | the caller WAV actually written, truncated at `delivered_audio_ms` |
| `inference_metrics` | one per stage | the LLM and TTS rows for the cancelled response with `status = "CANCELLED"` and the tokens/audio produced so far |
| caller turn record | updated | `planned_text`, `delivered_text`, `interrupted = true` |

`planned_text` is kept in the event payload and in the turn record but **not** in
`transcript_segments`: the transcript is what was heard (SPEC §25 "store actual text sent to TTS and
playback timing" is satisfied by the event payload + `inference_metrics`).

---

## 7. `ResponseValidator`

Every check is deterministic code. None of it asks a model anything.

```python
class ValidationFailureCode(enum.StrEnum):
    TOO_LONG = "TOO_LONG"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    EXTRA_FIELD = "EXTRA_FIELD"
    FORBIDDEN_IDENTIFIER = "FORBIDDEN_IDENTIFIER"
    META_LANGUAGE = "META_LANGUAGE"
    NEW_NUMBER = "NEW_NUMBER"
    NEW_ADDRESS_TOKEN = "NEW_ADDRESS_TOKEN"
    NEW_NAME = "NEW_NAME"
    WORLD_VALUE_LEAK = "WORLD_VALUE_LEAK"
    EMPTY = "EMPTY"
```

### 7.1 Length and schema (SPEC §24 items 1–3)

- The raw output is parsed as JSON; failure → `SCHEMA_INVALID`.
- Validated by the Pydantic model `CallerUtterance` with `extra="forbid"`; any additional key →
  `EXTRA_FIELD` (this is the "no unexpected structured fields" check).
- `utterance` stripped; empty → `EMPTY`.
- Token length is measured with the **same tokenizer the LLM uses**, obtained from
  `LLMClient.count_tokens`; `> max_response_tokens` (80, SPEC §22) → `TOO_LONG`. A character
  guard `len(utterance) > 400` is applied first so a pathological output never reaches the tokenizer.

### 7.2 Normalisation and tokenisation of Russian text

Applied once, producing `normalized_text` and a token list reused by §7.3–§7.6:

1. NFKC normalise; replace `ё` with `е`; lowercase for lexicon matching (the original casing is kept
   separately for §7.5).
2. Replace every Unicode dash and quote variant with `-` and `"`.
3. Split on `[^0-9A-Za-zА-Яа-я\-/]+`, keeping hyphens and slashes inside tokens (`27/2`, `дом-27`).
4. **Numeral folding.** Each token is mapped to a canonical numeric string when it is:
   - a digit run (`27`, `27/2`, `1985`);
   - a spelled-out Russian numeral, matched against a fixed lexicon
     `RU_NUMERAL_LEXICON` covering `ноль…девятнадцать`, the tens `двадцать…девяносто`, the hundreds
     `сто…девятьсот`, `тысяча`, and their case forms (`двадцати`, `двадцатью`, `двадцатая`, …),
     ordinals (`первый`, `второй`, … `двадцатый`) and the fraction words `половина`, `треть`,
     `четверть`. Adjacent numeral tokens are folded left-to-right into one value
     (`двадцать` `семь` → `27`; `сто` `двадцать` `пять` → `125`), and a folded run is recorded with
     both its canonical value and its source span.
   - The lexicon is a data file `backend/app/application/dialogue/ru_numerals.py`, not a regex, so
     it can be extended without touching the algorithm.
5. Digit/word equivalence: `27` and `двадцать семь` produce the same canonical value, so a model
   cannot evade the number check by spelling a digit out.

### 7.3 Forbidden identifiers (SPEC §24 item 4)

The forbidden set is built per turn:

- every `fact_id` in the `ScenarioVersion` (dotted form `people.victim_01.inside` and each dot
  segment longer than 3 characters);
- every enum literal of the domain: `KNOWN`, `UNKNOWN`, `INCORRECT_BELIEF`, `UNCERTAIN`,
  `SPONTANEOUS`, `ON_ASK`, `ONLY_IF_EXPLICITLY_ASKED`, `NEVER_DISCLOSE`, every `SessionEvent` type
  name, every session/stage state name, every `speech_act` value;
- the literal strings `ALLOWED_FACTS`, `ALREADY_REVEALED`, `WorldTruth`, `CallerBelief`,
  `world_value`, `caller_value`, `fact_id`, `semantic_confidence`.

Match is case-insensitive on the normalised text, on whole tokens and on any substring containing
`_` or `.` that appears in the set. A hit → `FORBIDDEN_IDENTIFIER`.

### 7.4 Meta-language lexicon (SPEC §24 item 6)

`META_LEXICON_RU` and `META_LEXICON_EN` are fixed word lists in
`backend/app/application/dialogue/meta_lexicon.py`; a match on a whole normalised token (or on a
listed two-word phrase) → `META_LANGUAGE`.

- RU: `симуляция`, `симулятор`, `сценарий`, `сценария`, `промпт`, `подсказка системы`,
  `модель`, `нейросеть`, `языковая модель`, `ассистент`, `помощник` (only in the self-referential
  phrases `я ассистент`, `как помощник`, `я — ассистент`), `искусственный интеллект`, `ИИ`,
  `контекст`, `инструкция`, `разрешённые факты`, `скрытые данные`, `оценка`, `баллы`,
  `тренажёр`, `упражнение`, `тест`, `система оценивания`, `разработчик`, `настройки`,
  `правила выше`, `в моём распоряжении`.
- EN: `simulation`, `scenario`, `prompt`, `system prompt`, `model`, `language model`, `llm`,
  `assistant`, `ai`, `context`, `instruction`, `allowed facts`, `hidden`, `scoring`, `score`,
  `token`, `roleplay`, `as an ai`, `i cannot`, `i'm sorry, but`.

Any Latin-script run of ≥ 3 letters that is not in a small `LATIN_ALLOWLIST` (vehicle marks,
`СМС`, `112` written as text) also raises `META_LANGUAGE`: a Russian caller has no reason to emit
English, and this catches refusal boilerplate the lexicon missed.

### 7.5 New entities (SPEC §24 item 5)

Build the **permitted value set** for this turn:

```
permitted = tokens(allowed fact caller values)
          ∪ tokens(already revealed caller values)
          ∪ tokens(operator utterances of the last `entity_lookback_turns` = 6 turns)
          ∪ PERSONA_WHITELIST
```

`PERSONA_WHITELIST` is derived from `CallerProfile`: the caller's own name and patronymic, their
declared age if `age_group` is numeric, and the fixed set `{"112", "01", "02", "03", "04"}`.
All four sources are run through §7.2, so spelled-out and digit forms are interchangeable.

Then, over the response tokens:

- **Numbers.** Every canonical numeric value not in `permitted` → `NEW_NUMBER`. Exempt: values
  reachable from a small `SMALL_COUNT_ALLOWLIST` (`0`–`3`) when the token is a bare count adjacent to
  a noun, because «двое» / «пара» wording is ordinary speech and is not an incident fact. The
  allowlist is config (`validator.small_count_allowlist`) and can be emptied for the §43 adversarial
  run.
- **Address-like tokens.** A token is address-like when it matches
  `ADDRESS_PATTERN = ^(д|дом|кв|квартира|корп|корпус|стр|строение|подъезд|этаж|ул|улица|пр|проспект|пер|переулок|ш|шоссе|б-р|бульвар|наб|набережная|пл|площадь)$`
  or when it is a digit run immediately following such a token, or when it is a capitalised token
  immediately preceding/following such a token (`улица Ленина`). Any address-like token or its
  attached value not in `permitted` → `NEW_ADDRESS_TOKEN`.
- **Capitalised names.** A token is name-like when, in the **original** casing, it starts with an
  uppercase Cyrillic letter, is ≥ 3 characters, and is not the first token of a sentence, not in
  `RU_COMMON_CAPITALIZED` (a small list of sentence-initial-only words and interjections), and not
  an address keyword. Not in `permitted` → `NEW_NAME`. Sentence-initial capitalised tokens are
  additionally checked against a Russian given-name/surname suffix heuristic
  (`-ов|-ев|-ин|-ский|-ко|-ич` or membership in `RU_GIVEN_NAMES`) so «Иван» at sentence start is
  still caught.

### 7.6 World-value leak check (D10)

The validator receives `forbidden_values` = every `world_value` and every `caller_value` in the
`ScenarioVersion` that is **not** in the current `AllowedFactsPackage` and not already revealed. Each
is normalised through §7.2. If any forbidden value's token sequence appears as a contiguous
subsequence of the response's token sequence → `WORLD_VALUE_LEAK`. Values shorter than 2 characters
and boolean values are skipped (they carry no information and would false-positive constantly).
This is the check SPEC §43 measures as `forbidden_fact_leak_rate`; its target at the deterministic
boundary is 0.

The validator may see these values because it is code. They never enter a prompt: `CallerPromptBuilder`
has no parameter that could carry them (D3).

### 7.7 Retry-once flow

```
attempt 1: generate -> validate
  ok    -> emit CALLER_RESPONSE_GENERATED, go to TTS
  fail  -> attempt 2
attempt 2: regenerate with the same prompt plus a correction message, temperature 0.3
  ok    -> emit CALLER_RESPONSE_GENERATED {attempt: 2}, go to TTS
  fail  -> deterministic fallback (7.8) + MODEL_FALLBACK_USED
```

The correction message appended for attempt 2 (`CALLER_REPAIR_PROMPT_RU`) names the category, never
the offending value (naming it would put the leaked value back into the context):

```
Твой предыдущий ответ отклонён проверкой: {failure_reason_ru}.
Ответь заново, короче, и утверждай только то, что есть в ALLOWED_FACTS.
```

`{failure_reason_ru}` is a fixed string per `ValidationFailureCode`, e.g. `NEW_NUMBER` →
«в ответе появилось число, которого тебе никто не сообщал».

There is exactly one retry (SPEC §24). A second failure never leads to a third call.

### 7.8 Deterministic fallback table, keyed by gate outcome

Selected by `FallbackTemplates.select(package, interpreted)`; first matching row wins.

| # | Gate / interpreter condition | Template (Russian) |
|:--|:--|:--|
| 1 | `speech_act == UNINTELLIGIBLE` or `semantic_confidence < 0.3` | «Простите, я не расслышала, повторите, пожалуйста.» |
| 2 | `allowed` non-empty | «{labels_and_values}.» — a templated statement of the allowed facts, rendered `{label_ru} — {caller_value_ru}` joined by «, », max 3 facts, the rest dropped and left unrevealed |
| 3 | `allowed` empty and every requested fact is `unavailable(reason=UNKNOWN)` | «Я не знаю, простите.» |
| 4 | `allowed` empty and some requested fact is `unavailable(reason=NEVER_DISCLOSE)` or withheld | «Я… я не могу сейчас сказать.» |
| 5 | `allowed` empty and some requested fact is `not_yet` | «Я пока не знаю.» |
| 6 | `requested_facts` empty, `speech_act ∈ {GREETING, OTHER}` | «Да, я слушаю.» |
| 7 | `speech_act == CLOSING` | «Хорошо. Спасибо.» |
| 8 | anything else | «Я не знаю, что сказать.» |

Row 2 is the only row that reveals facts, and it reveals them through the normal path: the text goes
to TTS, `CALLER_TTS_ENDED` fires, `FACTS_DELIVERED` follows. Rows 1 and 3–8 reveal nothing. Every
fallback also emits `MODEL_FALLBACK_USED {turn_id, stage, reason, failure_codes, template_row}`.
Templates are data in `backend/app/application/dialogue/fallback_templates_ru.py` and contain no
scenario values other than the caller values passed in for row 2.

---

## 8. Per-turn latency budget

Measured from `USER_SPEECH_ENDED` to the first **audible** caller audio. SPEC §27 targets: final demo
p50 < 1.2 s / p95 < 2.0 s; development acceptable p50 < 1.5 s / p95 < 2.5 s.

| # | Stage | Budget (ms) | Notes |
|:--|:--|--:|:--|
| 1 | Endpoint detection already elapsed | 0 | `endpoint_silence_ms` is before the measurement point by definition (the offset of `USER_SPEECH_ENDED` is the trimmed end of speech) |
| 2 | `ASRProvider.transcribe` of the finalized turn | 250 | GigaAM v3 CTC, single pass, ~4 s of audio; RTF target ≤ 0.08 measured by `benchmark_asr.py` |
| 3 | `DialogueInterpreter` LLM call (schema-constrained, ≤ 200 tokens) | 300 | prompt ≈ 2200 tokens; dominated by prefill; grammar constraint keeps output short |
| 4 | `FactAccessGate` | ≤ 5 | pure Python over ≤ 60 facts |
| 5 | `CallerResponseGenerator` — TTFT only | 200 | the generator streams; validation runs on the completed text (see below) |
| 6 | Generation to end of response (≤ 80 tokens) | 250 | at ≥ 40 tok/s; `benchmark_llm.py` measures the real rate |
| 7 | `ResponseValidator` | ≤ 10 | pure Python, no model |
| 8 | `TTSProvider.stream` first chunk | 200 | first-audio latency, `benchmark_tts.py` |
| 9 | Transport + browser jitter buffer to audible | 60 | **UNVERIFIED**; measured by `benchmark_e2e.py` |
| | **Total (baseline, validate-then-speak)** | **1275** | inside the development p50 target, above the final p50 target |

The gap between 1275 ms and the final-demo p50 of 1200 ms is closed by the levers below, not by
removing a stage.

**Permitted optimisation levers** (none of them violates SPEC §44):

1. **Sentence-level streaming validation.** `ResponseValidator` is applied to each completed sentence
   as it streams, behind the same interface, and TTS starts on the first validated sentence. This
   removes most of row 6 from the critical path (≈ −180 ms). If a later sentence fails validation,
   playback is cut exactly like a barge-in and the fallback template is spoken. D10 names this as
   permitted; the whole-response baseline remains the default until `benchmark_e2e.py` shows it is
   needed.
2. **Interpreter/generator prompt-cache reuse.** The system prompt, persona block and fact catalog
   are a stable prefix; llama-server KV reuse across turns of the same call removes most prefill
   (≈ −120 ms on rows 3 and 5).
3. **Warm everything.** Every provider's `warm_up()` runs before the session may start (SPEC §37), so
   no turn pays a first-inference cost.
4. **Smaller model.** SPEC §44 explicitly prefers a smaller/faster model over removing a boundary:
   dropping from Qwen3-8B to Qwen3-4B is allowed; dropping validation is not.
5. **Lower `tts_chunk_ms`** to get the first audible frame out sooner (row 8/9).

**Forbidden** as latency work, from SPEC §44 and D10: skipping `ResponseValidator`; merging the
interpreter and generator calls; handing the generator any scenario truth; caching a caller response
across turns; letting TTS run ahead of validation without the cut-on-failure rule of lever 1;
dropping any `SessionEvent`.

`speech_end_to_first_audio_ms` is computed per turn from the `USER_SPEECH_ENDED` offset and the
`CALLER_TTS_STARTED` audible offset and stored through `MetricsRecorder.record_turn_latency` (D9).
`CALLER_TTS_STARTED {turn_id, text, voice_id, provider, model_version, first_audio_offset_ms}` is
emitted when the **first frame is handed to the transport**, and `first_audio_offset_ms` carries the
transport's own estimate of when it became audible, so row 9 is measured rather than assumed.

---

## 9. Recording, transcripts and retention

### 9.1 Write path

Two WAV files per call, written incrementally by `SessionRecorder`
(`workers/voice_agent/recording/recorder.py`), 16 kHz mono s16le:

```
DATA_DIR/recordings/{session_id}/trainee-{call_id}.wav
DATA_DIR/recordings/{session_id}/caller-{call_id}.wav
```

- **Trainee**: the `_ingest` task tees every resampled `AudioFrame` into the trainee writer, so the
  file is continuous call audio including silence, and every `start_ms` is a plain byte offset.
- **Caller**: the `_respond` task tees every `TtsChunk.frame` that the `PlaybackHandle` actually
  captured. On barge-in the writer is truncated at `delivered_audio_ms` so the recording matches
  what was heard.

One `audio_segments` row per finalized turn and per caller utterance. `20-db-schema.md` owns the
column definitions for `audio_segments`; the values this write path sets are:

| Column | Value |
|:--|:--|
| `id` | uuid4 |
| `session_id` | the session |
| `speaker` | `TRAINEE` / `CALLER` |
| `file_path` | path above, relative to `DATA_DIR` |
| `format` | `'wav'` |
| `start_ms` | session-relative start (D9: session-relative, not file-relative) |
| `end_ms` | session-relative end |
| `sample_rate` | 16000 |
| `num_channels` | 1 |
| `byte_offset` | offset of `start_ms` inside the file, so a Range request needs no scan |
| `byte_length` | length of the segment |
| `purged_at` | `NULL` at write time; set by the retention purge (§9.2) |
| `created_at` | `Clock.now_utc()` |

One `transcript_segments` row per `ASR_FINAL` and per caller utterance (SPEC §19 fields, owned by
`20-db-schema.md`): `id`, `session_id`, `speaker`, `start_ms`, `end_ms`, `text`, `is_final`,
`confidence`, `asr_provider`, `asr_model`, `audio_segment_id`. Caller rows carry
`asr_provider = NULL` and `asr_model = NULL`; their `text` is the delivered text.
Partials (`ASR_PARTIAL`) are **not** written to `transcript_segments` — they exist only as events.

Ordering guarantee: the `audio_segments` row is inserted in the same transaction as the
`ASR_FINAL` / `CALLER_TTS_ENDED` event append, so `transcript_segments.audio_segment_id` is never
dangling and the report's click-transcript-to-seek (SPEC §29) always resolves.

The backend serves `/api/v1/sessions/{id}/audio/{audio_segment_id}` with HTTP Range using
`byte_offset` / `byte_length` (D9).

### 9.2 Retention and purge

- `RECORDING_RETENTION_DAYS` (env, default 30, `0` = never purge) is the retention window, counted
  from `simulation_sessions.completed_at` (or `created_at` for sessions that never completed).
- `python -m app.cli purge_recordings [--dry-run] [--older-than-days N]` walks sessions past the
  window, deletes the WAV files, sets `audio_segments.file_path = NULL` and
  `audio_segments.purged_at = now()`, and leaves the row so that offsets, transcripts, events and
  scores remain intact and reproducible (SPEC §28: the same event log must reproduce the same score).
- One row per purged audio segment; columns as defined in `20-db-schema.md` (`recording_purge_audit`).
  A `session_events` append is **not** used (the log is closed for a completed session); the audit row
  is written instead and logged at INFO.
- The report UI renders a purged segment as "audio deleted (retention)" and keeps the transcript.
- Nothing leaves the machine: recordings, transcripts, cards, scoring and models stay local
  (SPEC §41).

---

## 10. Profile bindings for the voice path

The provider selection per model profile is decided in `docs/hld/60-inference-ops.md`; repeated here
only as the binding the pipeline reads, so that a worker wiring `TurnPipeline` knows which adapter a
profile name resolves to.

| Profile | VADProvider | ASRProvider | TTSProvider | LLM |
|:--|:--|:--|:--|:--|
| `DEV_3060TI` | `SileroVAD` (CPU) | `GigaAMProvider` `v3_e2e_ctc` | `PiperTTS` (CPU) | Qwen3-4B via `LlamaCppClient` |
| `FINAL_3080TI_12GB` | `SileroVAD` (CPU) | `GigaAMProvider` `v3_e2e_ctc` | `Qwen3TTS` (fallback `PiperTTS`) | Qwen3-8B Q4_K_M |
| `FINAL_3080TI_16GB` | `SileroVAD` (CPU) | `GigaAMProvider` `v3_e2e_ctc` | `Qwen3TTS` or `ChatterboxTTS` (fallback `PiperTTS`) | Qwen3-8B Q4_K_M |
| gate / tests | `EnergyVAD` | `FakeASR` | `FakeTTS` | `FakeLLM` |

A TTS failure at runtime falls back to the profile's configured fallback provider, logs the failure
and emits `MODEL_ERROR {turn_id, stage: "TTS", error_kind}` followed by the fallback synthesis; it
never aborts the turn (SPEC §39).

---

## 11. Diagrams

- `docs/hld/puml/voice-pipeline.puml` — components and process boundaries.
- `docs/hld/puml/sequence-turn.puml` — one normal turn with every event emission.
- `docs/hld/puml/sequence-barge-in.puml` — the §6 procedure with the timing budget annotated.

## 12. Open items for the manager

1. Silero v5's fixed 512-sample window is confirmed; the **probability calibration** of
   `speech_start_threshold = 0.55` for this microphone/room is UNVERIFIED and must be tuned from a
   recorded corpus before the demo.
2. The browser-side jitter-buffer contribution (row 9 of §8, row 6 of §6.2) is UNVERIFIED and is
   measured by `benchmark_e2e.py`, not assumed.
3. Whether the shipped `gigaam` package exposes a streaming API is UNVERIFIED; the pseudo-streaming
   partial strategy of §4.5 is the baseline either way.
4. The Russian Piper voice id per profile is UNVERIFIED and is chosen in `60-inference-ops.md`.
