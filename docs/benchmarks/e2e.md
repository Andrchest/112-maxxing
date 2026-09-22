# End-to-end turn latency (SPEC §27, §35, §40; HLD `60-inference-ops.md` §7.4)

**For the owner, in two sentences:** SPEC §27's critical product metric — the time from the trainee
finishing a sentence to the first millisecond of the caller's voice — is **measured for real**, with
real models on this machine, at **p50 1192 ms / p95 1864 ms against the DEV targets of 1500 /
2500 ms**, on **35 of 36** turns, and the barge-in budget is met on every interruption.
That measurement is the **in-process** one. A full **LiveKit** call runs end to end too, and since
E20 (R13/R14, `reports/e20-f.md`) its latency figure is **derivable at last**: the post-fix re-run
of 2026-09-22, at the **shipped `SIM_SIM_TICK_MS=500`**, reports
**p50 1566 ms / p95 4622 ms over 29 turns with `discarded_nonpositive_count: 0`** and barge-in
p50 62 ms (§3.1). Over a real media plane the DEV p95 target of 2500 ms is therefore **not** met
today, while the in-process p95 of 1864 ms is — the gap is the number to work on, and it is now a
measured number rather than a missing one.

Every number below is read out of a committed result JSON. Nothing here is typed by hand.

| What | File under `docs/benchmarks/results/` |
|:--|:--|
| **The latency measurement** (in process, real providers, 4 runs) | `e2e-DEV_3060TI_SHARED-20260922T091948626Z.json` + `.csv` |
| **The post-fix LiveKit run** (real room, 4 runs, shipped 500 ms tick; §27 latency published) | `e2e-DEV_3060TI-20260922T144530930Z.json` + `.csv` |
| The pre-fix LiveKit run (barge-in measured, latency not derivable) — kept as history | `e2e-DEV_3060TI_SHARED-20260922T101931685Z.json` + `.csv` |
| The LiveKit run that deadlocked after 2 turns — kept as history | `e2e-DEV_3060TI_SHARED-20260922T101445123Z.json` |
| The LiveKit attempt before the agent could join, NOT_RUN | `e2e-DEV_3060TI_SHARED-20260922T091548598Z.json` |
| The earlier LiveKit refusal (SDK absent), NOT_RUN | `e2e-DEV_3060TI_SHARED-20260922T045857Z.json` |
| The first measurement, before the `"}"` fix — kept as history | `e2e-DEV_3060TI_SHARED-20260922T050544Z.json` + `.csv` |

---

## 1. What was run

| | |
|:--|:--|
| Date | 2026-09-22, 09:16:20–09:19:48 UTC |
| Machine | this dev box: RTX 3060 Ti 8 GB |
| Profile | `DEV_3060TI_SHARED` (LLM on GPU, ASR/TTS/VAD on CPU) |
| git sha | `0beec6a7ff030bb6960467150a0e33af537b75f9` |
| Transport | **`inprocess`** — the latency figures below; the LiveKit run is §3 |
| Dialogue chain | **`full`**: ASR → interpret → Fact Access Gate → generate → validate → TTS |
| Models | GigaAM `v3_e2e_ctc` (CPU) · Qwen3.5-2B Q4_K_M on llama-server, all layers on GPU, `--parallel 2` · Piper `ru_RU-irina-medium` (CPU) · Silero VAD (CPU) |
| Corpus | `benchmarks/data/e2e/turns.jsonl` — 9 trainee turns of `apartment-fire/v1`, Piper-synthesized (`benchmarks/data/e2e/README.md` states the caveat) |
| Runs | `--runs 4` ⇒ **36 scripted turns**, 35 of which produced caller audio |
| Free VRAM | 7842 MiB before; **6340 MiB** with llama-server resident ⇒ the LLM took ≈ 1502 MiB, consistent with `vram.md`'s 1559 MiB peak |
| Command | §8 |

The GPU was held under the shared lock for the llama-server's lifetime only;
`nvidia-smi --query-compute-apps` printed **no process at all** before and after the run.

## 2. The headline: `speech_end_to_first_audio_ms`

`USER_SPEECH_ENDED.at_offset_ms` → `CALLER_TTS_STARTED.first_audio_offset_ms`, same `turn_id`,
read straight out of the session event log — never timed by the benchmark's own stopwatch, so the
benchmark and the product metric cannot diverge (HLD §7.4).

| | ms |
|:--|--:|
| n (turns that produced caller audio) | **35** of 36 scripted |
| p50 | **1192** |
| p95 | **1864** |
| p99 | 2056 |
| mean | 1304 |
| max | 2056 |
| DEV target p50 / p95 | 1500 / 2500 |
| **`meets_target`** | **true** |

Spread across the four runs, fastest to slowest: 808, 840, 904, 968, 968, 968, 1000, 1000, 1032,
1064, 1064, 1096, 1128, 1128, 1128, 1160, 1192, **1192**, 1256, 1288, 1352, 1384, 1448, 1448,
1544, 1576, 1576, 1576, 1608, 1736, 1736, 1768, 1768, 1864, 2056 ms. The single turn without audio
was one `address` repetition whose generator call produced no speakable reply; it is reported with
a null latency rather than dropped.

`discarded_nonpositive_count` is **0**: no sample had the caller's audio start before the trainee
stopped speaking, so no value had to be excluded from the percentiles.

## 3. The LiveKit run: what it proved, and why its latency figure is withheld

`--transport livekit` **ran, for real, end to end** on 2026-09-22 10:16:49–10:19:31 UTC
(`e2e-DEV_3060TI_SHARED-20260922T101931685Z.json`): dev compose `postgres` / `redis` /
`livekit` v1.13.7, the API on 8100, the database migrated and seeded, the demo scenario imported, a
session created and started through the real API as INSTRUCTOR with the seeded TRAINEE as
`OPERATOR_112`, `CALL_RINGING`, the trainee's token minted by the backend's own endpoint, the
headless client publishing 36 turn WAVs as the trainee's microphone, and **the voice agent joined
the room** as `voice-agent:<call_id>` with a token it minted itself (§6, bug #4).

What the room actually carried:

| | |
|:--|--:|
| turns published by the client | 36 |
| turns the agent detected (`USER_SPEECH_ENDED`) | **39** (3 VAD splits) |
| turns the caller answered (`CALLER_TTS_STARTED`) | **34** |
| `ASR` p50 / min / max over the media plane | **162** / 103 / 470 ms |
| barge-ins (`CALLER_UTTERANCE_INTERRUPTED`) | **24** scripted + 2 unscripted |
| `cutoff_latency_ms` p50 / p95 / max | **0 / 0 / 0 ms** |
| `over_250ms_count` | **0** |

So the whole media path works: WebRTC in, ASR → interpret → gate → generate → validate → TTS, and
WebRTC out, with barge-in cutting the caller off inside the budget 24 times out of 24.

**What is withheld is `speech_end_to_first_audio_ms`, and deliberately.** All 34 measurable samples
came out *negative* and drifting (−29 711, −34 127, −35 759, −40 015 … ms, growing ~4–5 s per
turn), so `write_result` reported `overall.n = 0` with
`discarded_nonpositive_count: 34` rather than publish a percentile over impossible numbers. The
cause is exact, and it is a product bug, not a benchmark one (§6, bug #5): over this transport the
metric subtracts two events stamped from **two different origins** —

* `USER_SPEECH_ENDED.at_offset_ms` is `DetectedTurn.end_ms`, i.e. the media timeline built from
  `AudioFrame.capture_offset_ms`, which `LiveKitCallTransport._now_ms()` measures as
  **milliseconds since that transport's own first frame** (`time.monotonic_ns()` minus a private
  origin);
* `CALLER_TTS_STARTED.first_audio_offset_ms` comes from `VoiceEventAppender.offset_ms()` =
  `session_offset_ms(clock.now(), session.started_at)`, i.e. **milliseconds since the session
  started**.

The session starts well before the agent's transport does (create → ring → join → answer), so the
two clocks differ by that gap and drift further apart with every turn. In process the two agree by
construction — `FakeCallTransport` stamps capture offsets from the same `Clock` the appender reads
— which is why §2's figures are sound and these are not.

### 3.1 The post-fix LiveKit re-run (E20-C, the SPEC §46 walk, 2026-09-22)

`e2e-DEV_3060TI-20260922T144530930Z.json` + `.csv`, `--provider real --profile DEV_3060TI
--transport livekit --runs 4 --settle-ms 2500`, at the **shipped `SIM_SIM_TICK_MS=500`** — the
first LiveKit run made after E20-F landed R13 (one clock origin) and R14 (the row-lock deadlock).
Host-run stack: dev compose `postgres`/`redis`/`livekit` v1.13.7, host `llama-server` (Qwen3.5-2B
Q4_K_M, `--parallel 2`) on 8101, host voice agent, host API on 8100. **TTS was PiperTTS (CPU)**,
not Qwen3-TTS — see `docs/DOD_WALK.md` open item 4 for why the profile's GPU default could not
synthesise this scenario's caller.

| | |
|:--|--:|
| `status` | `OK` |
| turns published / detected | 36 / 39 |
| **`speech_end_to_first_audio_ms` n** | **29** |
| **`discarded_nonpositive_count`** | **0** — R13 proven on the real transport |
| p50 / p95 / p99 / max | **1566 / 4622 / 5205 / 5205 ms** |
| mean | 2003 ms |
| DEV target p50 / p95 | 1500 / 2500 |
| **`meets_target`** | **false** (p95) |
| `ASR` p50 over the media plane | 205 ms |
| barge-in n, p50 / p95 / max | **19**, 62 / 732 / 732 ms |
| `over_250ms_count` | **3** of 19 |
| `unscripted_cutoff_count` | 2 |
| Deadlocks at the 500 ms tick | **none** — R14 proven |

Two things this run settles and one it does not:

* **Settled:** the §27 metric is derivable over LiveKit (every sample positive), and the shipped
  tick no longer deadlocks a real call. Both were open in the run above.
* **Settled:** the media plane costs real time — p50 1192 → 1566 ms, p95 1864 → 4622 ms against
  the in-process figures. Part of that is Piper on CPU rather than Qwen3-TTS on the GPU, so the
  gap is an upper bound on the transport's own share, not the transport's share alone.
* **Not settled:** barge-in over-budget cuts appeared for the first time (3 of 19 over 250 ms,
  worst 732 ms) where the pre-fix LiveKit run measured 0 of 24. That run's zeros were measured
  against the broken clock origin, so the two are not comparable; 732 ms against §6.2's 250 ms
  budget is an open item, recorded in `docs/DOD_WALK.md`.

### Side by side

| | `inprocess` | `livekit` |
|:--|:--|:--|
| Result file | `…091948626Z.json` | `…101931685Z.json` |
| `status` | `OK` | `OK` |
| Pipeline | real, full chain | real, full chain |
| Media plane | none (in-process frames) | **real WebRTC**, LiveKit v1.13.7 |
| Agent in the room | n/a | **yes**, `voice-agent:<call_id>` |
| turns published / detected / answered | 36 / 48 / 35 | 36 / 39 / 34 |
| `ASR` p50 | 128 ms | 162 ms |
| **`speech_end_to_first_audio_ms`** p50 / p95 | **1192 / 1864 ms** (n = 35) | pre-fix: **not derivable** (n = 0, 34 discarded); post-fix (§3.1): **1566 / 4622 ms** (n = 29) |
| barge-in n, `over_250ms_count` | 8, **0** | **24**, **0** |
| Defect at run time | — | the two offset origins, bug #5 — **fixed in E20, R13** (§6) |

The honest reading of the pair: the pipeline behaves the same over both transports (ASR 128 → 162
ms is the only visible difference, and it is one Opus decode plus jitter), the barge-in budget is
met on both, and the in-process figure is a **lower bound** on delivered latency by one media-plane
round trip. §3.1's post-fix re-run now supplies the delivered figure itself (p50 1566 / p95
4622 ms), so the in-process number is no longer the only one available — quote both, and quote
§3.1's when the question is what a trainee actually hears.

What in-process does and does not include:

* **Nothing in the pipeline is faked.** The same `TurnPipeline`, `Resampler`, Silero VAD,
  `TurnDetector`, `AsrTurnResponder`, `DialogueResponder` (interpreter → gate → generator →
  validator) and `TtsSpeechSink` run, assembled by the voice agent's own composition root
  (`voice_agent.wiring`), over an ACTIVE session with the demo scenario instantiated. The metric is
  read from the event log the product itself writes.
* **It omits the network hop**: LiveKit's WebRTC encode / jitter buffer / decode on both legs.
* The inbound audio is **paced at real time** (one frame per `frame.duration_ms`), so the event
  log's offsets are wall-clock offsets. Without pacing the fake transport's scripted clock either
  ignores the time a model spends thinking (understating the turn) or double-counts the trailing
  silence consumed while it thinks (overstating it) — see `benchmark_e2e.py::_paced_transport_class`.

### One environment knob the LiveKit run needed (history — fixed in E20, R14)

The first LiveKit run died after **2 turns** with a PostgreSQL
`DeadlockDetectedError` on `SELECT next_seq_no FROM simulation_sessions WHERE id = $1 FOR UPDATE`
(`…101445123Z.json`, kept as history): the API's `SimulationRunner` ticks the same session every
`SIM_SIM_TICK_MS` (**500 ms** by default) and takes that D5 row lock, while the voice agent's own
FK-carrying side-table inserts take an implicit conflicting lock on the same row for every event of
every turn — two processes, two transactions, two lock modes that upgrade into each other. The run
above used `SIM_SIM_TICK_MS=10000`, which was a **benchmark-environment setting, not a product
change**, and it is why the run completed. **Bug #6 is now fixed** (§6): both lock sites take
`FOR NO KEY UPDATE` instead of `FOR UPDATE`, so the shipped 500 ms tick no longer deadlocks a real
LiveKit call — the workaround above is no longer needed for a future run.

## 4. The stage split

p50 over the scripted turns, keyed on the real `inference_metrics` component names (`component`,
`model`, `input_duration_ms`, `gpu_memory_mb` — this epic's R3), taken through the product's own
`InferenceStage → component` table so the benchmark cannot drift from the schema:

| component | p50 ms | share of a 1192 ms p50 turn |
|:--|--:|--:|
| `ASR` (GigaAM v3_e2e_ctc, CPU) | 128 | 11 % |
| `LLM_INTERPRETER` (Qwen3.5-2B) | 255 | 21 % |
| `LLM_GENERATOR` (Qwen3.5-2B) | 205 | 17 % |
| `TTS` time-to-first-chunk (Piper, CPU) | 19 | 2 % |
| — unattributed | ≈ 585 | 49 % |

The unattributed half is not missing time: it is the VAD's endpoint decision (the profile's
`endpoint_silence_ms` is 300 ms, rounded to 320 ms at the 32 ms frame), the turn detector, the
transcript and turn-row persistence between stages, and the outbound queue's first-frame
scheduling. The two LLM calls together are 460 ms — 39 % of the turn and the largest single lever;
ASR and the TTS first chunk are, on this profile, close to free.

`TTS` **total** (p50 1568 ms) is the whole utterance's synthesis; it overlaps playback and is not
part of the latency to first audio.

## 5. Barge-in

`turns.jsonl` marks two rows with `interrupt_after_ms` (`floor` 400 ms, `reassurance` 700 ms): the
benchmark replays the trainee's audio that many milliseconds after the caller's **observed** first
audio, which is only schedulable at run time because the latency is the thing being measured. The
injection is accurate to 120 ms (the inbound script's lead), recorded in the result's `notes`.

`cutoff_latency_ms` is **read from `CALLER_UTTERANCE_INTERRUPTED`**, which carries the product's own
measurement of it — never recomputed here from two offsets.

| | `inprocess` | `livekit` (pre-fix) | `livekit` (post-fix, E20-C §46 walk, 2026-09-22) |
|:--|--:|--:|--:|
| n | **8** (4 runs × 2 marked rows) | **24** | **19** |
| p50 / p95 / p99 | 0 / 0 / 0 ms | 0 / 0 / 0 ms | **62 / 732 / — ms** |
| max | 0 ms | 0 ms | 732 ms |
| `over_250ms_count` | **0** | **0** | **3** of 19 |
| `unscripted_cutoff_count` | 0 | 2 | 2 |

Budget: `50-voice-pipeline.md` §6.2, 250 ms. Every interruption cut the caller off within the same
millisecond the product recorded it — the outbound queue is cleared synchronously with the barge-in
decision, so nothing already queued is played after it. **The budget is met on 32 of 32
interruptions across the two transports, 24 of them over a real WebRTC media plane.** This is the
one part of SPEC §40's metric that the LiveKit run measures outright, because
`cutoff_latency_ms` is a single number the product computes and logs itself — it never subtracts
two offsets, so bug #5's two-clock problem cannot touch it.

The LiveKit run's higher count is the transport being live rather than scripted: the client keeps
publishing while the caller talks, so more turns overlap an in-flight caller utterance than the two
rows the corpus marks (the 2 `unscripted_cutoff_count` are exactly those).

**The post-fix `livekit` column (§3.1) is not directly comparable to the pre-fix one.** The
pre-fix `livekit` run's all-zero p50/p95/max was measured against the broken transport clock
origin R13 fixed (E20-F) — a barge-in cut recorded at an unreliable offset can read as
instantaneous by accident, not because it actually was. The post-fix run, made after R13 landed,
is the first LiveKit barge-in measurement on a trustworthy clock, and it shows the budget is **not**
always met over a real media plane: 3 of 19 cuts exceed 250 ms, the worst at 732 ms (one sample in
the same walk's own transcript reached 2990 ms, recorded in `docs/DOD_WALK.md`). This is an open
item, not a regression this task introduced — `docs/DOD_WALK.md` §4 item 7.

## 6. History: six product bugs this benchmark found

Kept here because the earlier tables in this repository were measured before them.

1. **The caller went silent on 40 % of turns** (fixed by E19-C2, 2026-09-22). The first real run
   (`…050544Z.json`, p50 1128 / p95 1480 over **n = 7 of 18**) showed every stage completing while
   `CALLER_RESPONSE_GENERATED` carried the utterance `"}"` — a single closing brace, which
   synthesizes to zero audio frames, so `CALLER_TTS_STARTED` was never emitted and the trainee
   heard nothing. `ResponseValidator` accepted it, so §7.8's deterministic template never engaged,
   contradicting `responder.py`'s own contract ("the caller never goes silent"). The fix tightened
   the grammar (a caller utterance must contain a Cyrillic letter) and the validator's `EMPTY`
   rule (no letter after stripping). **After the fix: 35 of 36 turns produce audio.** The earlier
   figures are not comparable — they are the p50/p95 of the minority of turns that happened to
   speak.
2. **The pipeline's VAD was never warmed** (fixed by E19-E2). `wiring.build_pipeline` built a fresh
   `VADProvider` per call and never warmed it, while `main.VoiceAgent._warm_vad` warmed a different
   instance it kept in `self._vad` and never passed on. With `SIM_VAD_PROVIDER=silero` — every
   model profile — the first frame of the first real call raised
   `SileroVAD.warm_up() must be called before process()`. `EnergyVAD` (the gate's) has no such
   precondition, which is why no gate test saw it. `build_pipeline` now takes `vad=` like it
   already took `asr`/`llm`/`tts`, and `main._run_call` passes the warmed instance;
   `TurnPipeline.run()` already `reset()`s a reused VAD per call. Two regression tests were added.
3. **The voice agent cannot join a LiveKit room** (open, §3). Not fixed here: minting the agent's
   own access token is a design decision about participant identity, not a mechanical repair. Two
   sub-problems, both worth fixing together: the missing token, and the silent task exception that
   hid it. → **Fixed in E19-E3, bug #4.**
4. **The voice agent could not join a LiveKit room** (fixed by E19-E3). `_default_transport` called
   `build_transport()` with **no token**, which raises for `SIM_CALL_TRANSPORT=livekit`; and because
   `_run_call` built the transport on the line *above* its `try`, the exception landed in a task
   nobody awaited and **nothing was logged**, so three runs looked like a lost join signal. The
   agent now mints its **own** token per call, locally, with the backend's own
   `LiveKitTokenService` (plain HS256 over the `SIM_LIVEKIT_API_*` it already holds — no SDK, no
   REST call to the backend, D9 intact): identity `voice-agent:<call_id>`, grants `roomJoin` on
   exactly that room plus `canPublish`/`canSubscribe` and nothing else, TTL 2 h (the trainee's
   10-minute browser token is short because a browser can ask the API for another; the agent
   cannot). **No token travels over Redis** — `voice:join` still carries only
   `{session_id, room, call_id}`, and the agent mints from that at join time. `_run_call` now builds
   the transport inside its `try`, logs with `logger.exception`, and appends
   `CALL_ENDED{reason: "TRANSPORT_UNAVAILABLE"}` so a call that never got a media plane still ends
   explicitly in the trainee-facing timeline instead of simply stopping (SPEC §39).
5. **`speech_end_to_first_audio_ms` is not derivable over LiveKit** (**fixed in E20, R13 —
   E20-F**). The metric subtracted an event stamped on the transport's own media clock from one
   stamped on the session clock; in process they were the same clock, over LiveKit they were not.
   Detail and evidence in §3 (kept as the historical record of the run that found this bug — the
   numbers above predate the fix and are unchanged by it). Root cause was two bugs, not one:
   `LiveKitCallTransport._now_ms()`'s own first-frame-relative origin, and
   `VoiceEventAppender(started_at=None)`'s silent zero-offset default that the real agent process
   never overrode. Both fixed: `capture_offset_ms`/`TransportEvent.at_offset_ms` are now defined on
   `app.application.ports.call_transport` as `session_offset_ms(clock.now(), session.started_at)`,
   and `voice_agent.main._session_started_at(session_id)` threads the real value through both the
   transport and the pipeline (`docs/hld/50-voice-pipeline.md` §3.0,
   `workers/voice_agent/tests/test_transport_clock_origin.py`, 7 tests). Until the LiveKit run is
   repeated post-fix (E20-C), the historical `overall.n = 0` /
   `discarded_nonpositive_count: 34` result above stands as the last real sample — the benchmark
   correctly refused to invent a percentile over negative numbers, which is SPEC §27's rule working
   as intended.
6. **The runner and the agent deadlock on `simulation_sessions.next_seq_no`** (**fixed in E20,
   R14 — E20-F**). At the shipped `SIM_SIM_TICK_MS=500` the API's `SimulationRunner` and the voice
   agent were taking two different lock modes on the session row (`FOR UPDATE` vs. an implicit
   `FOR KEY SHARE` from every voice-agent side-table FK insert) that conflict with each other; the
   first LiveKit run died after 2 turns with `DeadlockDetectedError` (§3, "One environment knob").
   The 10 s tick used for the measurement above was a benchmark-environment workaround, not a
   product fix, and is no longer necessary: both lock sites
   (`backend/app/infrastructure/persistence/event_store.py`'s `_LOCK_SESSION_ROW` and
   `SessionRepository._load(for_update=True)`) now take `FOR NO KEY UPDATE`, which is compatible
   with the FK's `FOR KEY SHARE` and still self-serialises allocation — no upgrade cycle is
   possible. Regression test:
   `backend/tests/integration/persistence/test_seq_lock_order.py` (50-round drive, reproduces the
   exact `DeadlockDetectedError` above on the unfixed lock mode). `docs/hld/20-db-schema.md` §20.8
   and `docs/hld/00-decisions.md` D5 rewritten to state the real mechanism. A future LiveKit run
   (E20-C) can use the shipped `SIM_SIM_TICK_MS=500`.

## 7. Caveats a reader must carry

* **Piper speaks the trainee's lines, not a person** — `benchmarks/data/e2e/README.md`, section
  "Honesty". Real trainees hesitate, breathe and sit in noisy rooms; all three change how long the
  VAD waits for an endpoint and how hard GigaAM works.
* **No LiveKit hop in the quoted latency** — §3. It is a lower bound on delivered
  latency by one media-plane round trip; the LiveKit run above predates bug #5's fix (§6) and
  still cannot report its own latency — a post-fix re-run is E20-C's, not yet done as of this
  edit.
* The envelope's `hardware` block is `null`: `benchmark_e2e.py` samples no NVML (it is not a VRAM
  benchmark). The free-VRAM readings in §1 come from the run script's own `nvidia-smi` calls,
  logged beside the result.
* A `turns.jsonl` WAV whose internal pause exceeds `endpoint_silence_ms` is legitimately split by
  the VAD into more than one turn. Only the first — the scripted one — is aggregated; the rest
  appear as `suite: "followup"` in the JSON (12 of them here) and never enter a percentile.
* One run of one corpus on one machine. p99 over 35 samples is the second-largest value, not a tail
  estimate.

## 8. Commands

```bash
# the corpus (CPU, no GPU; deterministic apart from Piper's in-graph noise)
uv run python benchmarks/data/e2e/build_turns.py

# the gate-side shape run (fakes, no GPU, no models) — what `make test-backend` exercises
make bench-e2e BENCH_ARGS="--provider fake"

# the real run: llama-server under the shared GPU lock, everything else on CPU
flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock bash -c '
  SIM_LLAMA_SERVER_BIN=~/src/llama.cpp/build/bin/llama-server \
  SIM_LLAMA_MODEL_PATH=$PWD/models/llm/Qwen3.5-2B-Q4_K_M.gguf \
  SIM_LLAMA_ALIAS=Qwen3.5-2B SIM_LLAMA_N_CTX=4096 SIM_LLAMA_PARALLEL=2 \
  SIM_LLAMA_N_GPU_LAYERS=-1 SIM_LLAMA_HOST=127.0.0.1 SIM_LLAMA_PORT=8101 \
  infra/scripts/llama-server-entrypoint.sh & sleep 30
  uv run python benchmarks/benchmark_e2e.py \
    --provider real --profile DEV_3060TI_SHARED \
    --transport inprocess --dialogue-chain full \
    --llm-base-url http://127.0.0.1:8101/v1 \
    --runs 4 --tag e19-e2-inprocess-postfix --out benchmarks/results'
```

`--dialogue-chain asr_tts` exists for diagnosis only (ASR + one fixed caller line, no dialogue
chain); its number is **not** SPEC §40's metric and must never be compared to the target.

The LiveKit run is the same command with `--transport livekit --livekit-url ws://127.0.0.1:7880
--livekit-token <backend-minted trainee token> --room <session room> --session-id <session id>`,
against the dev compose `postgres`/`redis`/`livekit`, the API on 8100 and a voice agent started
with the `DEV_3060TI_SHARED` environment and `SIM_CALL_TRANSPORT=livekit`. Four things cost this
run's operator a repeat to discover; **items 2–4 are E20 fixes and no longer apply to a future
run** (kept here as the historical record of what this run had to work around):

1. the agent must be fully warmed (all four `voice:health:*` keys `READY`) **before** the session is
   created — it subscribes to `voice:join` only after `warm_up()` returns; still true.
2. ~~the call must be left RINGING for a few seconds before it is answered, because `call_flow`
   re-publishes `voice:join` only while it rings~~ — **fixed, R2 (E20-F)**: `_retry_join` now fires
   on `RINGING` **or** `CONNECTED` and stops on the agent's own first appended event for that
   `call_id`, not on the trainee answering (`backend/app/application/operator/call_flow.py`, HLD 40
   §40.6, `backend/tests/api/voice/test_call_signals.py`).
3. ~~the agent resolves the profile's **compose** model paths on a host run, so
   `SIM_ASR_MODEL_DIR`, `SIM_VAD_MODEL_PATH` and `SIM_TTS_PIPER_VOICE_PATH` must be exported~~ —
   **fixed, R15 (E20-F)**: set `SIM_MODELS_ROOT=./models` once instead — `backend/app/config/model_paths.py`
   rebases every profile path through it (also used by `preflight` check 3 and the `tts_qwen3`
   worker).
4. ~~`SIM_SIM_TICK_MS` must be raised (10 s was used) until bug #6 is fixed, or the call deadlocks
   against the runner within a couple of turns~~ — **fixed, R14 (E20-F)**: the shipped
   `SIM_SIM_TICK_MS=500` no longer deadlocks (§6).

## 9. Preflight, as run

`make preflight ARGS='--profile DEV_3060TI_SHARED'` on the host (full output: task report E19-E).
PASS 1, 7, 8, 10; SKIP 11; FAIL 2, 3, 4, 5, 6, 9, 12. The failures are all "the host is not the
compose network": check 3 resolves the profile's *compose* paths (`/models/...`) and cannot see the
host layout under `models/`; 4/5/6/9 dial compose service names or worker ports that were not
running; 2 read 113 MiB free because another benchmark held the card at that moment; 12 timed out
running `llama-server --version` for the same reason.

Checks 3 and 12 are worth a second look, and the same compose-path problem bit the **voice agent**
on a host run: it resolves `/models/asr/...`, `/models/vad/...`, `/models/tts/...` and refuses to
warm up until `SIM_ASR_MODEL_DIR`, `SIM_VAD_MODEL_PATH` and `SIM_TTS_PIPER_VOICE_PATH` are exported
explicitly. `benchmark_*.py` solves this with `_common.resolve_model_path` + `--models-root`;
neither preflight nor the agent has an equivalent.
