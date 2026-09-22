#!/usr/bin/env python
"""End-to-end turn-latency benchmark (SPEC §27, §35, §40; HLD `60-inference-ops.md` §7.4).

**The number is read from the session event log**, never timed by the benchmark's own stopwatch:
`speech_end_to_first_audio_ms = CALLER_TTS_STARTED.first_audio_offset_ms −
USER_SPEECH_ENDED.at_offset_ms` for the same `turn_id`. That is SPEC §27's critical product
metric as the product itself writes it, so the benchmark and the product cannot diverge (HLD §7.4).
The stage split comes from the `inference_metrics` rows sharing the turn, rendered through the
product's own `PgMetricsRecorder.to_row()` so the columns are the real ones — `component`,
`model`, `input_duration_ms`, `gpu_memory_mb` (this epic's R3) — whether or not a database is in
the loop.

Two transports (`--transport`, additive to HLD §7.4):

* `inprocess` — the same `TurnPipeline` the product runs, driven through the voice agent's
  `FakeCallTransport` (`workers/voice_agent/voice_agent/transport/fake.py`) fed with the
  `turns.jsonl` WAV frames. No network hop, no LiveKit server; this is what the gate exercises.
* `livekit` — a headless client publishes the same WAVs into a real room and subscribes to the
  caller track. The LiveKit SDK is imported **only** from
  `workers/voice_agent/voice_agent/transport/headless_client.py` (D9,
  `backend/tools/check_imports.py` forbids `livekit` under `benchmarks/`); the client's own
  first-audio wall time is recorded as a **cross-check**, and the reported number stays the log's.

Barge-in sub-suite: a `turns.jsonl` row carrying `interrupt_after_ms` is interrupted that many ms
after the caller's first audio; `cutoff_latency_ms` p50/p95 and `over_250ms_count` are reported
(the §6.2 budget of `50-voice-pipeline.md`).
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
import wave
from pathlib import Path
from typing import Any

from _common import (
    Envelope,
    aggregate,
    ensure_backend_on_path,
    finish,
    load_jsonl,
    load_profile_for_bench,
    not_run,
    parse_common_args,
    percentile_nearest_rank,
    profile_config_subtree,
    resolve_model_path,
)

BENCHMARK = "e2e"
DEFAULT_TURNS = Path("benchmarks/data/e2e/turns.jsonl")
#: `50-voice-pipeline.md` §6.2's budget: a barge-in above this is counted, never silently averaged.
BARGE_IN_BUDGET_MS = 250
CALLER_LINE_RU = "Алло, я вас слушаю, говорите."
#: What the fake ASR "hears" on a gate-side shape run (--provider fake): a trainee question the
#: demo scenario's Fact Access Gate has a real answer for, so the whole chain has work to do.
FAKE_TRAINEE_LINE_RU = "Назовите адрес: улица и номер дома."


def _extra(parser: Any) -> None:
    parser.add_argument("--turns-file", type=Path, default=DEFAULT_TURNS)
    parser.add_argument("--transport", choices=("inprocess", "livekit"), default="inprocess")
    parser.add_argument("--scenario", default="apartment-fire", help="scenario slug (recorded)")
    parser.add_argument(
        "--livekit-url", default=None, help="LiveKit ws:// URL for --transport livekit"
    )
    parser.add_argument(
        "--livekit-token", default=None, help="a backend-minted trainee access token"
    )
    parser.add_argument("--room", default=None, help="room name for --transport livekit")
    parser.add_argument(
        "--session-id",
        default=None,
        help="the simulation session whose event log carries the turns (--transport livekit)",
    )
    parser.add_argument(
        "--clock",
        choices=("auto", "simulated", "wall"),
        default="auto",
        help="`simulated` = the FakeCallTransport's deterministic ingest clock, as fast as the "
        "event loop will run it (the gate's); `wall` paces the inbound script at real time so the "
        "ingest timeline IS the wall timeline (what a real model needs); `auto` picks wall for "
        "--provider real and simulated for --provider fake",
    )
    parser.add_argument(
        "--dialogue-chain",
        choices=("full", "asr_tts"),
        default="full",
        help="`full` = ASR -> interpret -> gate -> generate -> validate -> TTS, the whole SPEC "
        "§16 chain over a session, which is what SPEC §40's metric means; `asr_tts` skips the "
        "dialogue chain and speaks one fixed line (diagnosis only)",
    )
    parser.add_argument(
        "--llm-base-url",
        default="http://127.0.0.1:8101/v1",
        help="the llama-server the full chain's interpreter/generator dial (--dialogue-chain full, "
        "--provider real); loopback only (SPEC §41, validated by Settings)",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=1500,
        help="how long the call keeps feeding silence after the caller's answer has started "
        "before the transport disconnects",
    )
    parser.add_argument(
        "--turn-timeout-s",
        type=float,
        default=90.0,
        help="hard cap on one scripted call; a turn that exceeds it is reported with a null "
        "speech_end_to_first_audio_ms rather than hanging the run",
    )


# ---------------------------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------------------------


def _wav_frames(path: Path, config: Any) -> list[Any]:
    """`turns.jsonl`'s WAV as `AudioFrame`s at the config's frame size, offsets from zero."""
    from app.application.ports.call_transport import AudioFrame

    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit mono PCM")
        rate = handle.getframerate()
        pcm = handle.readframes(handle.getnframes())
    step = config.frame_samples * 2
    frames: list[Any] = []
    for index, start in enumerate(range(0, len(pcm) - step + 1, step)):
        frames.append(
            AudioFrame(
                pcm=pcm[start : start + step],
                sample_rate=rate,
                num_channels=1,
                samples_per_channel=config.frame_samples,
                capture_offset_ms=index * config.vad_frame_ms,
            )
        )
    return frames


def _silence(config: Any, duration_ms: int, offset_ms: int) -> list[Any]:
    ensure_backend_on_path()
    from app.application.testing.fakes import silence_frames

    return silence_frames(
        duration_ms=duration_ms,
        frame_samples=config.frame_samples,
        sample_rate=config.sample_rate,
        start_offset_ms=offset_ms,
    )


# ---------------------------------------------------------------------------------------------
# The in-process run
# ---------------------------------------------------------------------------------------------


def _paced_transport_class() -> Any:
    """`FakeCallTransport` whose inbound iterator runs at **real time** (E19-E, HLD 60 §7.4).

    `FakeCallTransport.inbound_audio()` yields the whole script as fast as the event loop will run
    it, advancing its `FakeClock` by each frame's duration. That is exactly right for the gate and
    exactly wrong for a real provider, and both obvious repairs are wrong too:

    * leaving it as it is **understates** the turn — a GigaAM transcription that costs 190 ms of
      wall time advances the clock by nothing, so `CALLER_TTS_STARTED.first_audio_offset_ms`
      lands almost on top of `USER_SPEECH_ENDED.at_offset_ms`;
    * adding wall time on top of the scripted advance (a `FakeClock` subclass reporting
      `scripted + wall`, which is what E19-A's draft did) **over**states it, because ingest and
      the responder run as concurrent tasks: the trailing silence is consumed *while* the models
      think, so that silence is counted once as script and once as wall.

    The only version that measures the product's own metric is the one where the two timelines are
    the same timeline: pace the inbound frames at their own duration. Then the plain `FakeClock`'s
    scripted offsets are real-time offsets, `speech_end_to_first_audio_ms` read from the event log
    is a real latency, and the inbound script can be grown *while the call runs*
    (`FakeCallTransport.script()` appends to the list `inbound_audio()` is iterating), which is
    what makes a barge-in schedulable relative to the caller's first audio.

    The subclass reaches into `_inbound` / `_inbound_active` / `_disconnected` / `yielded`: that is
    a deliberate, documented coupling to one test fake in one benchmark, not a new abstraction —
    `app.application.testing.fakes` belongs to the product and this script does not edit it.
    """
    from app.application.testing.fakes import FakeCallTransport

    class _RealTimeFakeCallTransport(FakeCallTransport):  # type: ignore[misc]
        async def inbound_audio(self) -> Any:
            """The scripted frames, one every `frame.duration_ms` of real time."""
            self._inbound_active = True
            loop = asyncio.get_running_loop()
            origin = loop.time()
            scripted_ms = 0
            index = 0
            try:
                while not self._disconnected.is_set():
                    if index >= len(self._inbound):
                        # The feeder appends lazily; hand the loop over and look again.
                        await asyncio.sleep(0.002)
                        continue
                    frame = self._inbound[index]
                    index += 1
                    self.yielded.append(frame)
                    yield frame
                    self._clock.advance_ms(frame.duration_ms)
                    scripted_ms += frame.duration_ms
                    behind = origin + scripted_ms / 1000.0 - loop.time()
                    await asyncio.sleep(behind if behind > 0 else 0)
            finally:
                self._inbound_active = False
                self._disconnected.set()

    return _RealTimeFakeCallTransport


class _ScriptWriter:
    """Appends frames to a live `FakeCallTransport` script with a continuous capture timeline."""

    def __init__(self, transport: Any, config: Any) -> None:
        self._transport = transport
        self._config = config
        self._offset_ms = 0

    @property
    def scripted_ms(self) -> int:
        """How much audio has been written so far."""
        return self._offset_ms

    @property
    def config(self) -> Any:
        """The `VoiceTurnConfig` the frame timeline is stamped against."""
        return self._config

    def write(self, frames: list[Any]) -> None:
        """Restamp `frames` onto the running timeline and hand them to the transport."""
        from app.application.ports.call_transport import AudioFrame

        restamped = []
        for frame in frames:
            restamped.append(
                AudioFrame(
                    pcm=frame.pcm,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                    samples_per_channel=frame.samples_per_channel,
                    capture_offset_ms=self._offset_ms,
                )
            )
            self._offset_ms += self._config.vad_frame_ms
        self._transport.script(restamped)

    def write_silence(self, duration_ms: int) -> None:
        """`duration_ms` of digital silence."""
        self.write(_silence(self._config, duration_ms, 0))


#: How far ahead of the playhead the silence pump keeps the script. Small on purpose: it is also
#: the worst-case lateness of a scheduled barge-in burst, which `notes` records.
_PUMP_LEAD_MS = 120
_PUMP_CHUNK_MS = 40
#: How much of the trainee WAV is replayed as the interrupting burst — long enough for
#: `barge_in_min_speech_ms` to be met several times over, short enough not to become a turn of
#: its own before the cutoff is observed.
_BARGE_IN_BURST_MS = 1200


async def _conduct_call(
    transport: Any,
    writer: _ScriptWriter,
    *,
    frames: list[Any],
    interrupt_after_ms: int | None,
    settle_ms: int,
    timeout_s: float,
) -> dict[str, Any]:
    """Drive one scripted call in real time and disconnect when it has what it came for.

    The shape of a call: 320 ms of pre-roll silence, the trainee's turn, then silence for as long
    as it takes the caller to start answering. For a barge-in row the trainee's audio is replayed
    `interrupt_after_ms` after the caller's **first audio** — which is only knowable at run time,
    hence the live script.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    writer.write_silence(320)
    writer.write(frames)
    burst = frames[: max(1, (_BARGE_IN_BURST_MS // writer.config.vad_frame_ms))]

    first_audio_at: float | None = None
    barged_at: float | None = None
    pending_interrupt = interrupt_after_ms is not None
    playbacks_at_interrupt = 0
    outcome: dict[str, Any] = {"timed_out": False, "barge_in_scheduled": False}
    try:
        while loop.time() < deadline:
            # Keep a small lead of silence so the iterator never starves and a scheduled burst is
            # never more than `_PUMP_LEAD_MS` late.
            played_ms = len(transport.yielded) * writer.config.vad_frame_ms
            while writer.scripted_ms - played_ms < _PUMP_LEAD_MS:
                writer.write_silence(_PUMP_CHUNK_MS)
            now = loop.time()
            if first_audio_at is None and transport.playbacks:
                first_audio_at = now
            if (
                pending_interrupt
                and first_audio_at is not None
                and now - first_audio_at >= (interrupt_after_ms or 0) / 1000.0
            ):
                writer.write(burst)
                pending_interrupt = False
                barged_at = now
                playbacks_at_interrupt = len(transport.playbacks)
                outcome["barge_in_scheduled"] = True
            if first_audio_at is None or pending_interrupt:
                await asyncio.sleep(0.01)
                continue
            if barged_at is not None and len(transport.playbacks) <= playbacks_at_interrupt:
                # Wait for the caller's reply to the interruption, but never past the deadline.
                await asyncio.sleep(0.01)
                continue
            settled_from = barged_at if barged_at is not None else first_audio_at
            if now - settled_from >= settle_ms / 1000.0:
                break
            await asyncio.sleep(0.01)
        else:
            outcome["timed_out"] = True
    finally:
        await transport.disconnect()
    return outcome


class _SpeakingStage:
    """`TranscribedTurnResponder` that hands one caller utterance to the real `TtsSpeechSink`.

    The interpret → gate → generate → validate chain in between is `DialogueResponder`'s and needs
    a persisted session to load its dialogue context from; it is measured on its own by
    `benchmark_llm.py`, and `config.dialogue_chain` records which of the two this run exercised so
    a reader can never mistake an ASR+TTS number for a full-turn one.
    """

    def __init__(self, sink: Any, text: str) -> None:
        self._sink = sink
        self._text = text

    async def respond_transcribed(self, transcribed: Any, context: Any) -> None:
        from app.application.dialogue.speech_sink import PlannedCallerUtterance
        from app.domain.caller.emotion import EmotionState
        from app.domain.enums import EmotionLabel

        planned = PlannedCallerUtterance(
            turn_id=transcribed.turn.turn_id,
            turn_index=transcribed.turn.turn_index,
            text=self._text,
            fact_ids=(),
            emotion=EmotionState(emotion=EmotionLabel.FRIGHTENED, stress_level=0.5),
            source="LLM",
        )
        with contextlib.suppress(asyncio.CancelledError):
            await self._sink.speak(planned, context)


async def _build_providers(args: Any, profile: Any) -> tuple[Any, Any, str | None]:
    """`(asr, tts, not_run_reason)` for the run."""
    if args.provider == "fake":
        from app.inference.asr.fake_asr import FakeASR
        from app.inference.tts.fake_tts import FakeTTS

        return FakeASR(script=["Квартира горит, помогите."] * 64), FakeTTS(), None

    asr_dir, asr_ok = resolve_model_path(profile.asr.model_path, args.models_root)
    if not asr_ok:
        return None, None, f"ASR model directory not found: {asr_dir}"
    from app.inference.asr.gigaam_provider import GigaAMProvider

    asr = GigaAMProvider(
        model_dir=str(asr_dir),
        model_version=profile.asr.model_version,
        device=profile.asr.device,
        compute_type=profile.asr.compute_type,
    )
    if profile.tts.provider == "piper":
        voice, voice_ok = resolve_model_path(
            profile.tts.fallback_model_path or profile.tts.model_path, args.models_root
        )
        if not voice_ok:
            return None, None, f"Piper voice not found: {voice}"
        from app.inference.tts.piper_tts import PiperTTS

        return asr, PiperTTS(voice_path=str(voice)), None
    from app.inference.tts.qwen3_tts import Qwen3TTS

    return asr, Qwen3TTS(base_url="http://127.0.0.1:8112", speaker=profile.tts.voice_id), None


def _infrastructure_placeholders() -> dict[str, str]:
    """`Settings`'s six required infrastructure fields, from the environment or unusable dummies.

    `--transport inprocess` opens no PostgreSQL connection, no Redis connection and no LiveKit
    room: it drives `FakeCallTransport` over an in-memory Unit of Work. `Settings` nevertheless
    refuses to be constructed without these six, so the real `SIM_*` values are used when the
    operator has them exported (a real run does — the Makefile exports them) and otherwise a
    deliberately unroutable placeholder stands in, so that a gate-side `--provider fake` run needs
    no environment at all. Nothing dials any of them; a value that leaked into a connection attempt
    would fail loudly on port 1 rather than reach a real service.
    """
    import os

    return {
        "database_url": os.environ.get(
            "SIM_DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused"
        ),
        "redis_url": os.environ.get("SIM_REDIS_URL", "redis://127.0.0.1:1/0"),
        "jwt_secret": os.environ.get("SIM_JWT_SECRET", "benchmark-placeholder-32-bytes!!!"),
        "livekit_url": os.environ.get("SIM_LIVEKIT_URL", "ws://127.0.0.1:1"),
        "livekit_api_key": os.environ.get("SIM_LIVEKIT_API_KEY", "unused"),
        "livekit_api_secret": os.environ.get("SIM_LIVEKIT_API_SECRET", "unused-placeholder-20+"),
    }


def _settings_for(args: Any, profile: Any) -> Any:
    """`Settings` for the full chain: the profile overlaid, then the host's real model paths.

    The profile names the *compose* paths (`/models/llm/...`); R1's `resolve_model_path` maps them
    onto this machine's `--models-root` layout. `call_transport` is pinned to `fake` because the
    in-process run drives `FakeCallTransport` directly, and `llm_base_url` is ours (a llama-server
    the operator started on loopback), never the compose service name — both are set explicitly so
    `apply_profile`'s "an explicitly-set field wins" rule leaves them alone.
    """
    from app.config.profile import apply_profile
    from app.config.settings import Settings

    if args.provider == "fake":
        # Every gate default is already the fake one (D13); `llm_base_url` has no default at all.
        return Settings(
            **_infrastructure_placeholders(),
            llm_base_url="http://127.0.0.1:8080/v1",
            call_transport="fake",
            vad_provider="energy",
            asr_provider="fake",
            llm_provider="fake",
            tts_provider="fake",
            tts_fallback_provider="none",
        )
    settings = apply_profile(
        Settings(
            **_infrastructure_placeholders(),
            llm_base_url=args.llm_base_url,
            call_transport="fake",
        ),
        profile,
    )
    update: dict[str, Any] = {}
    asr_dir, asr_ok = resolve_model_path(profile.asr.model_path, args.models_root)
    if not asr_ok:
        raise FileNotFoundError(f"ASR model directory not found: {asr_dir}")
    update["asr_model_dir"] = str(asr_dir)
    if profile.vad.provider == "silero":
        vad_path, vad_ok = resolve_model_path(profile.vad.model_path, args.models_root)
        if not vad_ok:
            raise FileNotFoundError(f"Silero VAD model not found: {vad_path}")
        update["vad_model_path"] = str(vad_path)
    if profile.tts.provider == "piper":
        voice, voice_ok = resolve_model_path(profile.tts.model_path, args.models_root)
        if not voice_ok:
            raise FileNotFoundError(f"Piper voice not found: {voice}")
        update["tts_piper_voice_path"] = str(voice)
    return settings.model_copy(update=update)


async def _run_inprocess(args: Any, profile: Any, envelope: Envelope) -> list[dict[str, Any]]:
    """Drive `turns.jsonl` through the real `TurnPipeline` over the fake transport.

    One call per turn: the metric SPEC §40 asks for is per-turn, and one session per turn keeps
    the read-back unambiguous (`USER_SPEECH_ENDED` → `CALLER_TTS_STARTED` for one `turn_id`).
    Providers are built **once** and reused across calls, so a model is loaded once per run and
    turn 1 does not carry the load time.
    """
    ensure_backend_on_path()
    rows = load_jsonl(args.turns_file)
    base = args.turns_file.parent
    settings = _settings_for(args, profile)
    paced = args.clock == "wall" or (args.clock == "auto" and args.provider == "real")

    if args.dialogue_chain == "full":
        providers, config = _build_full_chain_providers(settings)
    else:
        providers, config = await _build_asr_tts_providers(args, profile, settings)

    # Warm every provider BEFORE the first turn, so turn 1 does not carry a model load (HLD §4.2).
    # A warm-up failure is not suppressed for the VAD: `SileroVAD.process()` refuses to run
    # unwarmed, so a silent failure there would look like a pipeline that produced no turn.
    for name in ("vad", "asr", "tts", "llm"):
        provider = providers.get(name)
        if provider is None or not hasattr(provider, "warm_up"):
            continue
        if name == "vad":
            await provider.warm_up()
        else:
            with contextlib.suppress(Exception):
                await provider.warm_up()

    samples: list[dict[str, Any]] = []
    try:
        for run_index in range(max(1, args.runs)):
            for row in rows:
                samples.extend(
                    await _one_call(
                        row, base, config, settings, providers, run_index, args, paced=paced
                    )
                )
    finally:
        for name in ("asr", "tts", "llm", "vad"):
            provider = providers.get(name)
            if provider is not None:
                with contextlib.suppress(Exception):
                    await provider.close()
    envelope.note(
        f"inprocess: {len(rows)} turn(s) x {max(1, args.runs)} run(s), "
        f"dialogue_chain={args.dialogue_chain}, "
        f"inbound {'paced at real time' if paced else 'unpaced (simulated clock)'}"
    )
    return samples


def _build_full_chain_providers(settings: Any) -> tuple[dict[str, Any], Any]:
    """ASR + TTS + LLM through the voice agent's own `voice_agent.providers` (SPEC §19, D1).

    Nothing is constructed here that the product would not construct: the one module that knows a
    model's name is `voice_agent.providers`, and this benchmark asks it, exactly as
    `voice_agent.wiring` does.
    """
    from app.application.voice.config import voice_turn_config_from_settings
    from voice_agent.providers import build_asr, build_tts, build_vad
    from voice_agent.wiring import VoiceAgentDeps, build_dialogue_llm

    config = voice_turn_config_from_settings(settings)

    def _no_uow() -> Any:  # pragma: no cover - only the settings half of deps is used here
        raise RuntimeError("the per-call Unit of Work is built per call, not here")

    deps = VoiceAgentDeps.build(settings, _FrozenClock(), _no_uow)
    if settings.asr_provider == "fake":
        # `FakeASR()`'s script is empty by default, and `AsrTurnResponder` correctly ends a turn
        # with an empty transcript before the dialogue chain — so a gate-side shape run would
        # never reach interpret/gate/generate/TTS at all. Giving the fake a default line is the
        # same move `voice_agent.wiring.ScriptedFakeDialogueLLM` makes for the fake LLM, and for
        # the same reason: the chain must actually run with no weights anywhere (D13).
        from app.inference.asr.fake_asr import FakeASR

        asr: Any = FakeASR(script=[FAKE_TRAINEE_LINE_RU] * 64)
    else:
        asr = build_asr(settings)
    return {
        "asr": asr,
        "tts": build_tts(settings),
        "llm": build_dialogue_llm(deps),
        # ONE VAD for the whole run, warmed once and `reset()` per call. `voice_agent.wiring`'s
        # `build_pipeline` builds a fresh VAD per call instead and never warms it, which makes
        # `SileroVAD.process()` raise "warm_up() must be called before process()" — found by this
        # benchmark, reported to the manager, not fixed here (the fix is in the worker's wiring).
        "vad": build_vad(settings, config),
    }, config


class _FrozenClock:
    """A `Clock` that is never read — `build_dialogue_llm` only needs `deps.settings`."""

    def now(self) -> Any:  # pragma: no cover - never called
        raise RuntimeError("no clock is available outside a call")

    def monotonic_ms(self) -> int:  # pragma: no cover - never called
        raise RuntimeError("no clock is available outside a call")


async def _build_asr_tts_providers(args: Any, profile: Any, settings: Any) -> tuple[dict, Any]:
    """The diagnosis-only chain: ASR + one fixed caller line through the real `TtsSpeechSink`."""
    from app.application.voice.config import VoiceTurnConfig

    config = VoiceTurnConfig(
        endpoint_silence_ms=profile.voice_turn.endpoint_silence_ms,
        min_turn_ms=profile.voice_turn.min_turn_ms,
        tts_chunk_ms=profile.voice_turn.tts_chunk_ms,
    )
    asr, tts, reason = await _build_providers(args, profile)
    if reason is not None:
        raise RuntimeError(reason)
    return {"asr": asr, "tts": tts, "llm": None}, config


async def _one_call(
    row: dict[str, Any],
    base: Path,
    config: Any,
    settings: Any,
    providers: dict[str, Any],
    run_index: int,
    args: Any,
    *,
    paced: bool,
) -> list[dict[str, Any]]:
    """One call: pre-roll silence, the trainee WAV, silence until the caller answers, read the log.

    `paced` selects the real-time transport (`_paced_transport_class`) and, with it, the live
    script `_conduct_call` writes — including a barge-in burst placed relative to the caller's
    first audio, which cannot be pre-scripted because the latency is what is being measured.
    Unpaced is the gate's deterministic path and pre-scripts a fixed trailing silence.
    """
    from app.application.ports.metrics_recorder import NullMetricsRecorder
    from app.application.testing.fakes import FakeCallTransport

    frames = _wav_frames(base / row["path"], config)
    metrics = NullMetricsRecorder()

    if args.dialogue_chain == "full":
        store, clock, build_pipeline_for = _full_chain_call(settings, config, providers, metrics)
    else:
        store, clock, build_pipeline_for = _asr_tts_call(config, providers, metrics, row)

    transport_class = _paced_transport_class() if paced else FakeCallTransport
    transport = transport_class(clock=clock, inbound=(), outbound_queue_ms=config.outbound_queue_ms)
    writer = _ScriptWriter(transport, config)
    pipeline = build_pipeline_for(transport)

    outcome: dict[str, Any] = {}
    if paced:
        conductor = asyncio.create_task(
            _conduct_call(
                transport,
                writer,
                frames=frames,
                interrupt_after_ms=row.get("interrupt_after_ms"),
                settle_ms=args.settle_ms,
                timeout_s=args.turn_timeout_s,
            )
        )
        try:
            await asyncio.wait_for(pipeline.run(), timeout=args.turn_timeout_s + 30)
        finally:
            with contextlib.suppress(Exception):
                outcome = await conductor
    else:
        writer.write_silence(320)
        writer.write(frames)
        writer.write_silence(max(config.endpoint_silence_ms * 4, 1600))
        await asyncio.wait_for(pipeline.run(), timeout=120)

    samples = _read_back(store, metrics, row, run_index, args)
    for sample in samples:
        sample["timed_out"] = bool(outcome.get("timed_out", False))
        sample["barge_in_scheduled"] = bool(outcome.get("barge_in_scheduled", False))
    return samples


def _full_chain_call(
    settings: Any, config: Any, providers: dict[str, Any], metrics: Any
) -> tuple[Any, Any, Any]:
    """The whole SPEC §16 chain over one session: ASR → interpret → gate → generate → TTS.

    The session comes from `tests.unit.application.dialogue.conftest.make_store()` — an ACTIVE
    single-role session with the demo scenario instantiated, its caller belief and its world-engine
    state, behind the same `UnitOfWork` interface the backend and the voice agent use. That is what
    `DialogueContextLoader` needs, and it is why this path can run with no PostgreSQL while still
    exercising every stage: the benchmark reads its number out of the very event log the chain
    writes (R13 — no stage is bypassed to get a number).

    Everything downstream of `Settings` is built by `voice_agent.wiring`, the product's own
    composition root, with only the metrics recorder swapped for an in-memory one (the real
    `PgMetricsRecorder` would need `uow.inference_metrics`, i.e. a database; the columns the
    benchmark reports are still the schema's, via `_stage_rows`).
    """
    from app.application.testing.fakes import FakeClock
    from app.application.voice.events import VoiceEventAppender
    from app.application.voice.resampler import Resampler
    from app.application.voice.turn_detector import TurnDetector
    from app.application.voice.turn_pipeline import TurnPipeline
    from tests.unit.application.dialogue.conftest import make_store, make_uow_factory
    from voice_agent.wiring import (
        VoiceAgentDeps,
        build_dialogue_responder,
        build_responder,
        show_asr_partials,
    )

    store = make_store()
    clock = FakeClock(start=store.session.started_at)
    factory = make_uow_factory(store, clock)
    deps = VoiceAgentDeps.build(settings, clock, factory)

    def build(transport: Any) -> Any:
        vad = providers["vad"]
        vad.reset()
        dialogue = build_dialogue_responder(
            deps, llm=providers["llm"], metrics=metrics, tts=providers["tts"]
        )
        responder = build_responder(
            deps, asr=providers["asr"], metrics=metrics, next_stage=dialogue
        )
        return TurnPipeline(
            session_id=store.session.id,
            call_id=uuid.uuid4(),
            transport=transport,
            vad=vad,
            detector=TurnDetector(config),
            appender=VoiceEventAppender(
                session_id=store.session.id,
                uow_factory=factory,
                clock=clock,
                started_at=store.session.started_at,
            ),
            clock=clock,
            config=config,
            resampler=Resampler(
                target_sample_rate=config.sample_rate, frame_samples=vad.frame_samples
            ),
            responder=responder,
            asr=providers["asr"],
            show_asr_partials=show_asr_partials(deps),
        )

    return store, clock, build


def _asr_tts_call(
    config: Any, providers: dict[str, Any], metrics: Any, row: dict[str, Any]
) -> tuple[Any, Any, Any]:
    """ASR + TTS only (`--dialogue-chain asr_tts`): one fixed caller line, no dialogue chain."""
    from app.application.testing.fakes import FakeClock
    from app.application.voice.asr_responder import AsrTurnResponder
    from app.application.voice.events import VoiceEventAppender
    from app.application.voice.tts_speech_sink import TtsSpeechSink
    from app.application.voice.turn_detector import TurnDetector
    from app.application.voice.turn_pipeline import TurnPipeline
    from app.domain.common.ids import SessionId
    from app.inference.vad.energy_vad import EnergyVAD
    from tests.unit.application.voice.conftest import VoiceStore, uow_factory

    clock = FakeClock()
    store = VoiceStore()
    session_id = SessionId(uuid.uuid4())
    factory = uow_factory(store, clock)
    sink = TtsSpeechSink(
        provider=providers["tts"],
        metrics=metrics,
        clock=clock,
        config=config,
        uow_factory=factory,
    )

    async def stage_resolver(_session_id: Any) -> None:
        return None

    responder = AsrTurnResponder(
        asr=providers["asr"],
        metrics=metrics,
        clock=clock,
        config=config,
        stage_resolver=stage_resolver,
        timeout_ms=8000,
        next_stage=_SpeakingStage(sink, str(row.get("caller_text", CALLER_LINE_RU))),
    )

    def build(transport: Any) -> Any:
        return TurnPipeline(
            session_id=session_id,
            call_id=uuid.uuid4(),
            transport=transport,
            vad=EnergyVAD(
                frame_samples=config.frame_samples, required_sample_rate=config.sample_rate
            ),
            detector=TurnDetector(config),
            appender=VoiceEventAppender(
                session_id=session_id, uow_factory=factory, clock=clock, started_at=clock.now()
            ),
            clock=clock,
            config=config,
            responder=responder,
        )

    return store, clock, build


def _read_back(
    store: Any, metrics: Any, row: dict[str, Any], run_index: int, args: Any
) -> list[dict[str, Any]]:
    """The metric, from the event log and the `inference_metrics` rows — never a stopwatch.

    `cutoff_latency_ms` is likewise **read**, not derived: `CALLER_UTTERANCE_INTERRUPTED` carries
    the product's own measurement of it (`app.domain.events.catalog`'s payload keys), so the
    benchmark reports the number the trainee-facing timeline already contains rather than a second
    opinion computed from two offsets (R13, HLD §7.4).

    A `turns.jsonl` WAV whose internal pause exceeds `endpoint_silence_ms` is split by the VAD into
    more than one turn — real behaviour, not a defect. The first detected turn is the scripted one
    and the only one aggregated (`suite` `turn`/`barge_in`); the rest are kept as `followup` so the
    JSON still shows everything that happened without letting an unscripted turn into a percentile.
    """
    from app.domain.events.types import EventType

    ended: dict[str, int] = {}
    started_audio: dict[str, int] = {}
    cutoffs: dict[str, int] = {}
    for event in store.events:
        payload = event.payload
        turn_id = str(payload.get("turn_id") or event.correlation_id or "")
        if event.event_type is EventType.USER_SPEECH_ENDED and not payload.get("discarded_short"):
            ended[turn_id] = int(payload["at_offset_ms"])
        elif event.event_type is EventType.CALLER_TTS_STARTED:
            started_audio[turn_id] = int(payload["first_audio_offset_ms"])
        elif (
            event.event_type is EventType.CALLER_UTTERANCE_INTERRUPTED
            and payload.get("cutoff_latency_ms") is not None
        ):
            cutoffs[turn_id] = int(payload["cutoff_latency_ms"])

    rows_by_turn = _stage_rows(metrics)
    samples: list[dict[str, Any]] = []
    for index, (turn_id, speech_end) in enumerate(sorted(ended.items(), key=lambda item: item[1])):
        first_audio = started_audio.get(turn_id)
        stages = rows_by_turn.get(turn_id, {})
        scripted = index == 0
        sample: dict[str, Any] = {
            "id": f"{row['id']}:{turn_id[:8]}",
            "turn_file": row["path"],
            "run_index": run_index,
            "suite": "turn" if scripted else "followup",
            "transport": args.transport,
            "speech_end_to_first_audio_ms": (first_audio - speech_end)
            if first_audio is not None
            else None,
            "asr_ms": stages.get("ASR"),
            "interpret_ms": stages.get("LLM_INTERPRETER"),
            "generate_ms": stages.get("LLM_GENERATOR"),
            "tts_first_chunk_ms": stages.get("TTS_TTFT"),
            "tts_ms": stages.get("TTS"),
            "interrupt_after_ms": row.get("interrupt_after_ms"),
            "cutoff_latency_ms": cutoffs.get(turn_id),
        }
        if scripted and row.get("interrupt_after_ms") is not None:
            # Only a row the corpus MARKED as a barge-in is in that sub-suite. A cutoff can also
            # happen unscripted — the VAD splits a WAV and the second half talks over the caller's
            # answer — and that number is kept on the sample but counted separately, never mixed
            # into a budget comparison the corpus did not ask for.
            sample["suite"] = "barge_in"
        samples.append(sample)
    return samples


def _stage_rows(metrics: Any) -> dict[str, dict[str, Any]]:
    """`turn_id -> {component: total_latency_ms}` under the REAL column names (R3).

    `_COMPONENT_OF_STAGE` is imported from `app.infrastructure.metrics.pg_metrics_recorder` — the
    very table the product uses to turn an `InferenceStage` into `inference_metrics.component` —
    so the benchmark cannot drift from the schema (`ASR`, `LLM_INTERPRETER`, `LLM_GENERATOR`,
    `TTS`, `VAD`).
    """
    from app.infrastructure.metrics.pg_metrics_recorder import _COMPONENT_OF_STAGE

    out: dict[str, dict[str, Any]] = {}
    for metric in getattr(metrics, "metrics", ()):
        component = _COMPONENT_OF_STAGE.get(metric.stage, str(metric.stage))
        bucket = out.setdefault(str(metric.turn_id), {})
        bucket[component] = metric.total_latency_ms
        if component == "TTS" and metric.ttft_ms is not None:
            bucket["TTS_TTFT"] = metric.ttft_ms
    return out


# ---------------------------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------------------------


#: The sample suites a percentile is computed over: one scripted trainee turn per `turns.jsonl`
#: row. `followup` — a turn the VAD split out of the same WAV — is reported but never aggregated
#: (`_read_back`'s docstring).
SCRIPTED_SUITES = ("turn", "barge_in")


def _aggregates(samples: list[dict[str, Any]], profile: Any) -> dict[str, Any]:
    scripted = [s for s in samples if s.get("suite") in SCRIPTED_SUITES]
    measured = [s for s in scripted if s["speech_end_to_first_audio_ms"] is not None]
    # A value <= 0 means the caller's audio began before the trainee stopped speaking: that reply
    # belongs to an EARLIER turn and the VAD split this one out of the same WAV. Counted, never
    # averaged — a negative latency in a percentile would be a fabricated number (SPEC §27).
    values = [
        s["speech_end_to_first_audio_ms"] for s in measured if s["speech_end_to_first_audio_ms"] > 0
    ]
    overall = aggregate(values)
    targets = profile.latency_targets
    payload: dict[str, Any] = {
        "overall": overall,
        "followup_turn_count": len(samples) - len(scripted),
        "discarded_nonpositive_count": len(measured) - len(values),
        "per_stage_p50_ms": {
            stage: percentile_nearest_rank(
                [s[stage] for s in scripted if s.get(stage) is not None], 50
            )
            for stage in ("asr_ms", "interpret_ms", "generate_ms", "tts_first_chunk_ms", "tts_ms")
        },
        "latency_targets": {"p50_ms": targets.p50_ms, "p95_ms": targets.p95_ms},
        "meets_target": bool(
            overall["p50"] is not None
            and overall["p95"] is not None
            and overall["p50"] <= targets.p50_ms
            and overall["p95"] <= targets.p95_ms
        ),
    }
    barge = [
        s["cutoff_latency_ms"]
        for s in samples
        if s.get("suite") == "barge_in" and s.get("cutoff_latency_ms") is not None
    ]
    if barge:
        payload["barge_in"] = {
            **aggregate(barge),
            "over_250ms_count": sum(1 for value in barge if value > BARGE_IN_BUDGET_MS),
        }
    payload["unscripted_cutoff_count"] = sum(
        1
        for s in samples
        if s.get("suite") != "barge_in" and s.get("cutoff_latency_ms") is not None
    )
    return payload


# ---------------------------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------------------------


async def run(args: Any) -> Envelope:
    profile = load_profile_for_bench(args.profile)
    config = profile_config_subtree(profile, "asr", "tts", "voice_turn", "latency_targets")
    config.update(
        {
            "provider_mode": args.provider,
            "transport": args.transport,
            "scenario": args.scenario,
            "turns_file": str(args.turns_file),
            "dialogue_chain": args.dialogue_chain,
            "clock": args.clock,
            "llm_base_url": args.llm_base_url if args.provider == "real" else None,
            "settle_ms": args.settle_ms,
            "runs": args.runs,
            "seed": args.seed,
            "tag": args.tag,
        }
    )
    if not args.turns_file.is_file():
        return not_run(
            BENCHMARK, args.profile, f"turns corpus not found: {args.turns_file}", config=config
        )
    if not load_jsonl(args.turns_file):
        return not_run(
            BENCHMARK, args.profile, f"turns corpus is empty: {args.turns_file}", config=config
        )

    if args.transport == "livekit":
        reason = _livekit_preflight(args)
        if reason is not None:
            return not_run(BENCHMARK, args.profile, reason, config=config)

    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    envelope.note(
        "speech_end_to_first_audio_ms is read from the session event log "
        "(USER_SPEECH_ENDED -> CALLER_TTS_STARTED.first_audio_offset_ms), not timed here"
    )
    if args.transport == "inprocess" and args.dialogue_chain == "full":
        envelope.note(
            "dialogue_chain=full: ASR -> interpret -> Fact Access Gate -> generate -> validate -> "
            "TTS, every stage the product runs, over an ACTIVE session with the demo scenario "
            "instantiated behind the same UnitOfWork interface the backend uses (no PostgreSQL)"
        )
    elif args.transport == "inprocess":
        envelope.note(
            "dialogue_chain=asr_tts (diagnosis only): the interpret/gate/generate stages are "
            "SKIPPED and one fixed caller line is spoken; do not compare this to SPEC §27's target"
        )
    else:
        config["dialogue_chain"] = "full (whatever the running voice-agent is wired with)"
    if args.transport == "inprocess" and (
        args.clock == "wall" or (args.clock == "auto" and args.provider == "real")
    ):
        envelope.note(
            "inbound audio is paced at real time, so the FakeClock's scripted offsets ARE "
            f"wall-clock offsets; a scheduled barge-in burst can be up to {_PUMP_LEAD_MS} ms late "
            "(the silence pump's lead)"
        )
    try:
        if args.transport == "livekit":
            envelope.samples = await _run_livekit(args, envelope)
        else:
            envelope.samples = await _run_inprocess(args, profile, envelope)
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"

    if envelope.samples:
        envelope.aggregates = _aggregates(envelope.samples, profile)
    elif envelope.status == "OK":
        envelope.status = "NOT_RUN"
        envelope.reason = "the pipeline produced no completed turn"
    return envelope


def _livekit_preflight(args: Any) -> str | None:
    """`--transport livekit` needs the headless client, a URL, a token, a room and a session."""
    missing = [
        name
        for name, value in (
            ("--livekit-url", args.livekit_url),
            ("--livekit-token", args.livekit_token),
            ("--room", args.room),
            ("--session-id", args.session_id),
        )
        if not value
    ]
    if missing:
        return (
            f"--transport livekit needs {', '.join(missing)}: a voice-agent must already be in "
            "the room for that session (dev compose LiveKit on 7880), and the metric is read "
            "back from ITS session event log"
        )
    try:
        from voice_agent.transport.headless_client import HeadlessTraineeClient  # noqa: F401
    except Exception as exc:
        return f"the headless LiveKit client is unavailable: {type(exc).__name__}: {exc}"
    # The client imports the SDK inside its methods (D1: `livekit` is an optional extra that no
    # `pyproject.toml` in this workspace declares today), so importing the class proves nothing —
    # without this check an absent SDK surfaces as a FAILED half-way through the run instead of the
    # honest NOT_RUN it is. `find_spec` rather than an import statement: `check_imports.py` forbids
    # a static `livekit` import anywhere under `benchmarks/`.
    import importlib.util

    if importlib.util.find_spec("livekit") is None:
        return (
            "the livekit SDK is not installed: `sim-voice-agent`'s `transport-livekit` extra is "
            "declared but not present in this venv. Run `make deps-livekit`, or use "
            "--transport inprocess."
        )
    return None


async def _run_livekit(args: Any, envelope: Envelope) -> list[dict[str, Any]]:
    """Publish the turn WAVs into a real room; read the metric back from the session event log.

    The headless client's own first-audio wall time is kept beside the logged number as
    `first_audio_wall_ms_crosscheck` — HLD §7.4 is explicit that the *reported* number comes from
    the event log, so a subscriber's clock can only ever corroborate it.
    """
    from voice_agent.transport.headless_client import HeadlessTraineeClient

    rows = load_jsonl(args.turns_file)
    base = args.turns_file.parent
    client = HeadlessTraineeClient(url=args.livekit_url, token=args.livekit_token, room=args.room)
    published: list[tuple[dict[str, Any], int, float | None]] = []
    await client.connect()
    try:
        for run_index in range(max(1, args.runs)):
            for row in rows:
                interrupt_after_ms = row.get("interrupt_after_ms")
                if interrupt_after_ms is not None and published:
                    # A barge-in: start talking `interrupt_after_ms` after the caller's first audio
                    # of the PREVIOUS turn, i.e. over the top of the caller's answer. The previous
                    # iteration already waited for that first audio, so the delay is measured from
                    # (approximately) now.
                    await asyncio.sleep(int(interrupt_after_ms) / 1000.0)
                elif published:
                    # Let the caller finish before the next question, the way a dispatcher would.
                    await asyncio.sleep(args.settle_ms / 1000.0)
                await client.publish_wav(base / row["path"], turn_id=f"{row['id']}:{run_index}")
                crosscheck = await client.wait_for_caller_audio()
                published.append((row, run_index, crosscheck))
    finally:
        await client.close()

    samples = await _read_event_log(args)
    # Attribution is by **publish order**: the client waits for the caller's first audio after each
    # WAV, so detected turns and published rows line up one-to-one — unless the VAD splits a WAV
    # whose internal pause exceeds `endpoint_silence_ms`, which shifts everything after it. The
    # `notes` line below says so; a detected turn past the end of the published list is `followup`.
    for index, sample in enumerate(samples):
        if index < len(published):
            row, run_index, crosscheck = published[index]
            sample["id"] = f"{row['id']}:{sample['id'].split(':')[-1]}"
            sample["turn_file"] = row["path"]
            sample["run_index"] = run_index
            sample["interrupt_after_ms"] = row.get("interrupt_after_ms")
            sample["first_audio_wall_ms_crosscheck"] = crosscheck
            if row.get("interrupt_after_ms") is not None:
                sample["suite"] = "barge_in"
        else:
            sample["suite"] = "followup"
            sample["first_audio_wall_ms_crosscheck"] = None
    envelope.note(
        f"livekit: published {len(published)} turn(s) into room {args.room!r}; the reported number "
        "is the session event log's, and a row is attributed to a detected turn by publish order "
        "(a VAD-split WAV shifts that attribution; sample count vs published count says whether "
        f"it happened: {len(samples)} detected vs {len(published)} published)"
    )
    return samples


async def _read_event_log(args: Any) -> list[dict[str, Any]]:
    """`USER_SPEECH_ENDED` -> `CALLER_TTS_STARTED` per turn, straight out of `session_events`."""
    import os

    import sqlalchemy as sa
    from app.db.models.events import InferenceMetric, SessionEvent
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("SIM_DATABASE_URL")
    if not url:
        raise RuntimeError("--transport livekit reads the event log; set SIM_DATABASE_URL")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            events = (
                await connection.execute(
                    sa.select(
                        SessionEvent.event_type, SessionEvent.payload, SessionEvent.correlation_id
                    )
                    .where(SessionEvent.session_id == args.session_id)
                    .order_by(SessionEvent.seq_no)
                )
            ).all()
            metrics = (
                await connection.execute(
                    sa.select(
                        InferenceMetric.component,
                        InferenceMetric.turn_index,
                        InferenceMetric.total_latency_ms,
                        InferenceMetric.ttft_ms,
                    ).where(InferenceMetric.session_id == args.session_id)
                )
            ).all()
    finally:
        await engine.dispose()

    stages: dict[int, dict[str, Any]] = {}
    for component, turn_index, total_latency_ms, ttft_ms in metrics:
        bucket = stages.setdefault(int(turn_index or -1), {})
        bucket[str(component)] = total_latency_ms
        if str(component) == "TTS" and ttft_ms is not None:
            bucket["TTS_TTFT"] = ttft_ms

    ended: dict[str, tuple[int, int]] = {}
    started_audio: dict[str, int] = {}
    interrupted: dict[str, int] = {}
    for event_type, payload, correlation_id in events:
        turn_id = str(payload.get("turn_id") or correlation_id or "")
        if event_type == "USER_SPEECH_ENDED" and not payload.get("discarded_short"):
            ended[turn_id] = (int(payload["at_offset_ms"]), int(payload.get("turn_index", -1)))
        elif event_type == "CALLER_TTS_STARTED":
            started_audio[turn_id] = int(payload["first_audio_offset_ms"])
        # The product measures the cutoff itself; the benchmark reports that number (R13).
        elif (
            event_type == "CALLER_UTTERANCE_INTERRUPTED"
            and payload.get("cutoff_latency_ms") is not None
        ):
            interrupted[turn_id] = int(payload["cutoff_latency_ms"])

    samples: list[dict[str, Any]] = []
    # Ordered by the turn's own end offset, which is the order the trainee actually spoke them —
    # what `_run_livekit`'s publish-order attribution zips against.
    for turn_id, (speech_end, turn_index) in sorted(ended.items(), key=lambda item: item[1][0]):
        first_audio = started_audio.get(turn_id)
        bucket = stages.get(turn_index, {})
        cutoff = interrupted.get(turn_id)
        samples.append(
            {
                "id": f"livekit:{turn_id[:8]}",
                "turn_file": "",
                "run_index": 0,
                "turn_index": turn_index,
                "suite": "barge_in" if cutoff is not None else "turn",
                "transport": "livekit",
                "speech_end_to_first_audio_ms": (first_audio - speech_end)
                if first_audio is not None
                else None,
                "asr_ms": bucket.get("ASR"),
                "interpret_ms": bucket.get("LLM_INTERPRETER"),
                "generate_ms": bucket.get("LLM_GENERATOR"),
                "tts_first_chunk_ms": bucket.get("TTS_TTFT"),
                "tts_ms": bucket.get("TTS"),
                "cutoff_latency_ms": cutoff,
            }
        )
    return samples


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
