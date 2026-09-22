#!/usr/bin/env python
"""VRAM benchmark (SPEC §26, §27, §35, §40; HLD `60-inference-ops.md` §7.5).

Measures idle model residency and peak during a realistic sequence, in the order §7.5 fixes:

    nothing loaded → load VAD → load ASR → load TTS → wait for llama-server
    → sample idle → run `--turns N` realistic turns → sample peak → idle again

NVML is sampled every 100 ms for the whole run; **NVML unavailable ⇒ `status: "NOT_RUN"`,
`reason: "NVML unavailable"` and no numbers** (§7.5). Every load step is wrapped: an OOM or any
exception at step *k* yields `status: "PARTIAL"` with the deltas of the steps that *did* complete
and a `reason` naming step *k* and the free MB at that moment — a CUDA OOM is an honest result,
never a retry with a smaller number typed by hand.

Reported: `baseline_used_mb`, `idle_after_load_mb`, `peak_mb`, `project_peak_mb`
(= `peak_mb − baseline_used_mb`), `free_min_mb` and the per-service deltas `vad_delta_mb`,
`asr_delta_mb`, `tts_delta_mb`, `llm_delta_mb`.

`project_peak_mb` is the value a human copies into the profile's `measured_peak_vram_mb` together
with `measured_at`. The script prints that line ready to paste and **never edits a profile file**
— a measurement entering configuration is a human decision (HLD §7.5).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from _common import (
    Envelope,
    NvmlSampler,
    ensure_backend_on_path,
    finish,
    load_profile_for_bench,
    not_run,
    parse_common_args,
    profile_config_subtree,
    resolve_model_path,
)

BENCHMARK = "vram"
WARMUP_TEXT_RU = "Проверка связи."
TURN_TEXT_RU = "Квартира горит, пришлите пожарных немедленно."


def _extra(parser: Any) -> None:
    parser.add_argument(
        "--turns", type=int, default=20, help="realistic turns after the idle sample"
    )
    parser.add_argument(
        "--start-tts-worker",
        action="store_true",
        help="(qwen3_tts only) the caller accepts responsibility for a worker this run starts; "
        "without it the worker is expected to be running already",
    )
    parser.add_argument(
        "--tts-base-url", default="http://127.0.0.1:8112", help="Qwen3-TTS worker base URL"
    )
    parser.add_argument(
        "--llama-server-bin", default=None, help="llama-server binary (env: SIM_LLAMA_SERVER_BIN)"
    )
    parser.add_argument("--model-path", type=Path, default=None, help="GGUF override")
    parser.add_argument(
        "--nvml",
        choices=("auto", "stub"),
        default="auto",
        help="`stub` forces a deterministic zero sampler — test-only, for the gate's shape run",
    )


class _Steps:
    """The §7.5 load sequence, each step recorded with the VRAM it added."""

    def __init__(self, sampler: NvmlSampler) -> None:
        self._sampler = sampler
        self.baseline_used_mb: int | None = None
        self.deltas: dict[str, int | None] = {}
        self.failed_step: str | None = None
        self.failure: str | None = None
        self._last: int | None = None

    def mark_baseline(self) -> None:
        reading = self._sampler.read()
        self.baseline_used_mb = reading[0] if reading else None
        self._last = self.baseline_used_mb

    async def step(self, name: str, load: Any) -> Any:
        """Run one load step; record its delta, or stop the sequence with an honest reason."""
        if self.failed_step is not None:
            self.deltas[f"{name}_delta_mb"] = None
            return None
        try:
            result = await load()
        except BaseException as exc:
            reading = self._sampler.read()
            free = reading[1] if reading else None
            self.failed_step = name
            self.failure = f"step {name!r} failed with {type(exc).__name__}: {exc}; free_mb={free}"
            self.deltas[f"{name}_delta_mb"] = None
            return None
        reading = self._sampler.read()
        used = reading[0] if reading else None
        self.deltas[f"{name}_delta_mb"] = (
            used - self._last if used is not None and self._last is not None else None
        )
        self._last = used if used is not None else self._last
        return result


async def run(args: Any) -> Envelope:
    profile = load_profile_for_bench(args.profile)
    config = profile_config_subtree(profile, "llm", "asr", "tts", "vad")
    config.update(
        {
            "provider_mode": args.provider,
            "turns": args.turns,
            "runs": args.runs,
            "seed": args.seed,
            "tag": args.tag,
            "nvml": args.nvml,
        }
    )

    sampler = NvmlSampler(stub=args.nvml == "stub")
    if not sampler.available:
        return not_run(BENCHMARK, args.profile, "NVML unavailable", config=config)

    envelope = Envelope(
        benchmark=BENCHMARK,
        status="OK",
        profile=args.profile,
        config=config,
        hardware=sampler.hardware,
    )
    envelope.note(f"nvml_mode={sampler.mode}")
    sampler.start()
    steps = _Steps(sampler)
    steps.mark_baseline()
    started_processes: list[Any] = []

    try:
        vad = await steps.step("vad", lambda: _load_vad(args, profile))
        asr = await steps.step("asr", lambda: _load_asr(args, profile))
        tts = await steps.step("tts", lambda: _load_tts(args, profile))
        llm_handle = await steps.step("llm", lambda: _load_llm(args, profile, started_processes))
        idle_reading = sampler.read()
        idle_after_load_mb = idle_reading[0] if idle_reading else None

        turns_done = 0
        turns_failure: str | None = None
        if steps.failed_step is None:
            turns_done, turns_failure = await _run_turns(args, asr, tts, llm_handle, sampler)
        peak_mb = sampler.peak_used_mb
        final_reading = sampler.read()

        envelope.samples.append(
            {
                "id": "sequence",
                "run_index": 0,
                "suite": "vram",
                "baseline_used_mb": steps.baseline_used_mb,
                "idle_after_load_mb": idle_after_load_mb,
                "peak_mb": peak_mb,
                "project_peak_mb": (peak_mb - steps.baseline_used_mb)
                if peak_mb is not None and steps.baseline_used_mb is not None
                else None,
                "free_min_mb": sampler.min_free_mb,
                "idle_after_turns_mb": final_reading[0] if final_reading else None,
                "turns": turns_done,
                **steps.deltas,
            }
        )
        if steps.failed_step is not None:
            envelope.status = "PARTIAL"
            envelope.reason = steps.failure
        elif turns_failure is not None:
            envelope.status = "PARTIAL"
            envelope.reason = f"turns failed after {turns_done} completed: {turns_failure}"
        for provider in (vad, asr, tts):
            if provider is not None and hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception as exc:
                    envelope.note(f"close failed: {type(exc).__name__}: {exc}")
    except Exception as exc:
        envelope.status = "FAILED"
        envelope.reason = f"{type(exc).__name__}: {exc}"
    finally:
        _stop_all(started_processes, envelope)
        peak, count = sampler.stop()
        envelope.note(f"nvml_samples={count} peak_used_mb={peak}")

    if envelope.samples:
        envelope.aggregates = _aggregates(envelope.samples)
        _print_paste_line(envelope)
    elif envelope.status == "OK":
        envelope.status = "NOT_RUN"
        envelope.reason = "the sequence produced no sample"
    return envelope


# ---------------------------------------------------------------------------------------------
# Load steps
# ---------------------------------------------------------------------------------------------


async def _load_vad(args: Any, profile: Any) -> Any:
    if args.provider == "fake":
        from app.inference.vad.energy_vad import EnergyVAD

        return EnergyVAD(frame_samples=512, required_sample_rate=16000)
    path, exists = resolve_model_path(profile.vad.model_path, args.models_root)
    if not exists:
        raise FileNotFoundError(f"VAD model not found: {path}")
    from app.inference.vad.silero_vad import SileroVAD

    vad = SileroVAD(model_path=str(path))
    await vad.warm_up()
    return vad


async def _load_asr(args: Any, profile: Any) -> Any:
    if args.provider == "fake":
        from app.inference.asr.fake_asr import FakeASR

        return FakeASR(script=["Квартира горит."] * 512)
    path, exists = resolve_model_path(profile.asr.model_path, args.models_root)
    if not exists:
        raise FileNotFoundError(f"ASR model not found: {path}")
    from app.inference.asr.gigaam_provider import GigaAMProvider

    asr = GigaAMProvider(
        model_dir=str(path),
        model_version=profile.asr.model_version,
        device=profile.asr.device,
        compute_type=profile.asr.compute_type,
    )
    await asr.warm_up()
    return asr


async def _load_tts(args: Any, profile: Any) -> Any:
    if args.provider == "fake":
        from app.inference.tts.fake_tts import FakeTTS

        return FakeTTS()
    if profile.tts.provider == "piper":
        path, exists = resolve_model_path(
            profile.tts.fallback_model_path or profile.tts.model_path, args.models_root
        )
        if not exists:
            raise FileNotFoundError(f"Piper voice not found: {path}")
        from app.inference.tts.piper_tts import PiperTTS

        tts = PiperTTS(voice_path=str(path))
    else:
        if args.start_tts_worker:
            raise RuntimeError(
                "--start-tts-worker is not implemented here: start the tts_qwen3 worker on 8112 "
                "yourself (make run-tts-qwen3) and stop it yourself, so this script never signals "
                "a process it did not start"
            )
        from app.inference.tts.qwen3_tts import Qwen3TTS

        # `Qwen3TTS`'s default `timeout_ms` (20 000) is a PER-TURN production timeout, sized for
        # an already-warm worker (SPEC §27's turn budget). This load step's first call is the
        # worker's *cold* load-then-generate (real runs, E19-D/E19-D3: 2.4-43 s depending on
        # caching), which is exactly what the profile's own `warmup.timeout_ms` (60 000 here) is
        # FOR — HLD 60 §4.2's warm-up sequence already budgets for a cold load, this benchmark's
        # load step should too. Found as a real bug: a 20 000 ms client timeout produced
        # `TtsTimeoutError` with 6311 MB still free (E19-D3,
        # vram-DEV_3060TI-20260922T085937512Z.json) — not a VRAM constraint, a too-short client
        # timeout for a cold worker. Fixed to reuse `profile.warmup.timeout_ms` for this one
        # client instance (the same instance is then reused for the `--turns` loop, where per-turn
        # calls are already warm and fast).
        tts = Qwen3TTS(
            base_url=args.tts_base_url,
            speaker=profile.tts.voice_id,
            timeout_ms=profile.warmup.timeout_ms,
        )
    await tts.warm_up()
    return tts


async def _load_llm(args: Any, profile: Any, started: list[Any]) -> Any:
    if args.provider == "fake":
        from app.inference.llm.fake_llm import FakeLLM

        return FakeLLM(["Готово."] * 512)
    model_path = args.model_path
    if model_path is None:
        model_path, exists = resolve_model_path(profile.llm.model_path, args.models_root)
        if not exists:
            raise FileNotFoundError(f"GGUF not found: {model_path}")
    from _llama import start_server
    from app.inference.llm.llama_cpp_client import LlamaCppClient

    tmp = TemporaryDirectory(prefix="bench-vram-")
    started.append(tmp)
    handle = start_server(
        Path(model_path),
        Path(tmp.name),
        parallel=profile.llm.parallel_slots,
        ctx_size=profile.llm.n_ctx * profile.llm.parallel_slots,
        binary=args.llama_server_bin,
    )
    started.append(handle)
    return LlamaCppClient(
        base_url=f"{handle.base_url}/v1",
        model_name=Path(model_path).stem,
        n_ctx=profile.llm.n_ctx,
        default_timeout_ms=profile.llm.request_timeout_ms,
    )


def _stop_all(started: list[Any], envelope: Envelope) -> None:
    """Stop every process this script started — and only those (MACHINE RULES)."""
    from _llama import terminate

    for item in reversed(started):
        try:
            if hasattr(item, "process"):
                terminate(item.process)
                envelope.note("llama-server terminated")
            elif hasattr(item, "cleanup"):
                item.cleanup()
        except Exception as exc:
            envelope.note(f"stopping {item!r} failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------------------------
# The realistic turns
# ---------------------------------------------------------------------------------------------


async def _run_turns(
    args: Any, asr: Any, tts: Any, llm: Any, sampler: NvmlSampler
) -> tuple[int, str | None]:
    """`--turns N` ASR + LLM + TTS turns, run concurrently up to the profile's parallel slots.

    Returns `(turns_done, failure)`. A turn that raises stops the loop and is reported as
    `failure`, but `turns_done` still reflects every turn that genuinely completed — a real OOM
    (or any other exception) partway through the turns phase must not discard the load-phase
    deltas the run already measured (the same "an honest PARTIAL, not a silent FAILED" rule
    `_Steps.step()` already applies to the load steps, HLD §7.5, SPEC §27).
    """
    ensure_backend_on_path()
    from app.application.ports.llm import ChatMessage
    from app.application.ports.tts import TtsVoiceSpec

    # `voice_id=""` — not `"bench"`, a free-form string `Qwen3TTS.stream()` rejects (it validates
    # any *non-empty* `voice_id` against the four vendor speakers and falls back to its
    # constructed default speaker only when empty). Found as a real bug in this task (E19-D3):
    # once the earlier `_load_tts` timeout fix let a real run reach this function, it FAILED with
    # `samples: []` (all load-phase deltas lost) on `TtsVoiceSpec.voice_id='bench' is not one of
    # the vendor speakers`. Same fix as `benchmark_tts.py`'s `_synthesize`/`_cancel` (E19-D).
    voice = TtsVoiceSpec(voice_id="", speaking_rate=1.0)
    pcm = b"\x00\x00" * 16000  # one second of 16 kHz silence: the same shape every turn

    async def one(index: int) -> None:
        request_id = f"bench-vram-{index}"
        if asr is not None:
            await asr.transcribe(pcm, 16000, request_id=request_id)
        if llm is not None:
            await llm.complete(
                [ChatMessage(role="user", content=TURN_TEXT_RU)],
                request_id=request_id,
                max_tokens=48,
                temperature=0.2,
                timeout_ms=30_000,
            )
        if tts is not None:
            async for _chunk in tts.stream(
                TURN_TEXT_RU, voice, request_id=request_id, max_chunk_ms=20
            ):
                pass
        sampler.read()

    done = 0
    for index in range(max(0, args.turns)):
        try:
            await one(index)
        except Exception as exc:
            return done, f"{type(exc).__name__}: {exc}"
        done += 1
    return done, None


# ---------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------


def _aggregates(samples: list[dict[str, Any]]) -> dict[str, Any]:
    row = samples[0]
    return {
        "n": len(samples),
        **{
            key: row.get(key)
            for key in (
                "baseline_used_mb",
                "idle_after_load_mb",
                "peak_mb",
                "project_peak_mb",
                "free_min_mb",
                "vad_delta_mb",
                "asr_delta_mb",
                "tts_delta_mb",
                "llm_delta_mb",
            )
        },
    }


def _print_paste_line(envelope: Envelope) -> None:
    """The line a human pastes into the profile — printed, never written (HLD §7.5)."""
    value = envelope.aggregates.get("project_peak_mb")
    if value is None:
        return
    today = datetime.now(UTC).date().isoformat()
    print(
        f"measured_peak_vram_mb: {value}  # measured_at: {today}, "
        f"benchmarks/results/{envelope.benchmark}-{envelope.profile}-*.json",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_common_args(BENCHMARK, argv, extra=_extra, description=__doc__)
    envelope = asyncio.run(run(args))
    return finish(envelope, args.out)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
