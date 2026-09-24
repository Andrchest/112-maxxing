# VoIP one-way delay and load sweep (ТЗ ¶161 REQ-2139, ¶160 REQ-2138; HLD `80-telephony.md`
§80.8.3, §80.11) — I3 E6a + E6f

Machine: `andreipc-B660M-DS3H-DDR4` (the dev box). Single-call date: **2026-09-24** (E6a). Sweep
date: **2026-09-24** (E6f, same day, later commit). Script: `benchmarks/benchmark_voip.py`. GPU:
not used on any path (no model runs). Code: branch `feat/i3-requirements-alignment`; the E6a
single-call envelopes' `git_sha` is `366a2e5` **plus the uncommitted E6a working tree**, the E6f
sweep envelopes' `git_sha` is `2008fea` (E6e, HEAD at sweep time) **plus the uncommitted E6f
working tree** — both stated per-envelope, never assumed. Raw envelopes:
`docs/benchmarks/results/voip-*`.

ТЗ ¶161: «задержка … (VoIP) не более 150 мс» — the owner's reading is «постараемся». 80 §80.11's
**falsification checkpoint** is: `sip-livekit` one-way p95 > 150 ms, or a softphone unable to
complete a call, re-issues E6e as plan B (direct RTP) or the Asterisk fallback before E6b–E6d are
staffed.

## Method

Mouth-to-ear on one host clock (`ToneBurstProbe`, `voice_agent/transport/sip/softphone.py`): the
sender emits 20 ms 8 kHz frames (PCMA on the SIP leg) with a 100 ms 1 kHz burst every 2 s; the far
end detects each burst's first loud sample and stamps it; delay = arrival − send at sample
resolution, 30 bursts per run after 1 s of warm-up silence. p50/p95/p99 are the nearest-rank
percentiles of `_common.aggregate`.

**What the number excludes:** a softphone's own capture/playout buffering (typically 40–80 ms in a
desktop softphone; ours in `--headset` mode adds sox's buffers) and a hardware phone's adaptive
jitter buffer (the RTU T16R adapts up to 300 ms, REQ-2422). It includes the gateway's own jitter
buffer (`SIM_SIP_JITTER_MS=40`) and its 20 ms playout clock, the 8↔48 kHz resampling, Opus in the
SFU, and the LiveKit SDK's send queue and receive buffer.

## Results

| Path | What is measured | Run (envelope) | Bursts | one-way p50 | p95 | max | Target p95 ≤ 150 |
|:--|:--|:--|--:|--:|--:|--:|:--|
| `sip-loopback` | UA → in-process gateway → echo `999` → UA, loopback; **round trip / 2** | `…T084900409Z` | 30/30 | **0.16 ms** | **0.25 ms** | 0.25 ms | met |
| `sip-livekit` | UA → gateway (jitter 40 ms) → `LiveKitRoomBridge` → SFU → probe participant | `…T084532086Z` | 30/30 | **110.2 ms** | **120.3 ms** | 122.6 ms | **met** |
| `sip-livekit` | same, repeat | `…T084638339Z` | 30/30 | **107.2 ms** | **110.1 ms** | 113.5 ms | **met** |
| `livekit-only` | publisher → SFU → subscriber (no SIP leg) | `…T084741099Z` | 30/30 | 80.9 ms | 89.7 ms | 90.3 ms | met |
| `sip-livekit` (superseded) | first run, jitter buffer priming bug (below) | `…T084037853Z` | 30/30 | 121.1 ms | 158.9 ms | 159.7 ms | not met |
| `livekit-only` (same session) | first run | `…T084151955Z` | 30/30 | 80.4 ms | 98.5 ms | 100.2 ms | met |

`sip-loopback` RTP: 3 050 packets each way, 0 lost, interarrival jitter 0.48 ms. The SFU was the
project's own dev compose `livekit` service (`livekit/livekit-server:v1.13.7`, ports 7880–7882,
dev placeholder keys), started for these runs with `docker compose -f infra/docker-compose.yml up
-d --no-deps livekit` and stopped and removed afterwards; no other stack service ran.

**The superseded run, stated rather than hidden.** The first `sip-livekit` run came out at p95
158.9 ms. Its steady state was ~121 ms, and the two bursts inside the first 5 s (159.7, 158.9 ms)
set the p95 (nearest rank 29 of 30). Diagnosis: the gateway's jitter buffer started playout only
once *three* frames (60 ms) were waiting, not the configured 40 ms — an off-by-one in
`JitterBuffer.push` (`len > depth_frames`), fixed to `len >= depth_frames` in the same epic; the
two runs after the fix are the table's `sip-livekit` rows. An experiment varying the bridge's
`AudioSource` queue (100/40/20 ms) moved `sip-livekit` by no more than run-to-run noise
(112 / 117 / 124 ms p50 over 15 bursts) and was not adopted.

## Falsification checkpoint (80 §80.11)

- **Delay:** `sip-livekit` one-way p95 = **120.3 ms** and **110.1 ms** (two runs) ≤ 150 ms — the
  checkpoint does **not** fire on delay. Headroom is ~30–40 ms, and the excluded softphone buffering
  (above) can eat it: a desktop softphone's own 40–80 ms would put mouth-to-ear at roughly
  150–200 ms. The SIP leg costs ~25–30 ms over `livekit-only`, most of it the 40 ms jitter buffer;
  `SIM_SIP_JITTER_MS=20` is the first knob if a real softphone run lands above target.
- **Call completion:** our own softphone (`python -m voice_agent.tools.softphone`) registered and
  completed calls to `999` against the gateway on 5060 (UDP and TCP; REGISTER 401 → 200, INVITE
  100/180/200/ACK, 6 s and 5 s of two-way audio, 0 RTP loss, BYE 200) — see the E6a report.
  `--headset` was not exercised (no audio device used on this bench; the tone/capture mode ran).
- **Third-party interop:** `baresip` is **NOT_RUN** — not installed on this machine, and nothing is
  downloaded (80 §80.13). Interop against a foreign SIP stack is therefore **unproven**.

## Load sweep (`--concurrent N`, I3 E6f, HLD 80 §80.8.3 "Load"; REQ-2139, REQ-2138 «≥ 20
concurrent»)

**Method addendum.** `--concurrent N` runs N simultaneous calls concurrently (`asyncio.gather`)
and reports the same one-way-delay percentiles over every burst of every call, plus RTP packet
loss, jitter, and gateway/SFU CPU sampled from `/proc` by a **captured PID**
(`_common.ProcCpuSampler`: `subprocess.Popen.pid`, `docker inspect .State.Pid`, or the harness's
own `os.getpid()` — never a `pgrep`/name-pattern match).

- **`sip-loopback`** (the gateway-only reference) launches the REAL standalone gateway process
  (`python -m voice_agent.sip_gateway`, E6a/E6e's own entry point — the exact code the
  `sip-gateway` compose service runs) as its own OS process, on ports distinct from any other
  running instance. `gateway_cpu_percent` is that subprocess alone.
- **`sip-livekit`** keeps the gateway in-process, as the single-call path does, so N softphones +
  N `LiveKitRoomBridge` listener pairs (one dedicated LiveKit room per call) all run inside this
  benchmark's own Python process; `gateway_cpu_percent` there is therefore the **whole harness
  process** (UA-driving loop included), not gateway-isolated CPU — stated in every such envelope's
  `notes`, not hidden. `sfu_cpu_percent` is the real dev LiveKit container's own PID via
  `docker compose ... ps` + `docker inspect`. Every `sip-livekit` `--concurrent` run staggers its
  call starts by a documented ramp (`_CONCURRENT_RAMP_S` = 150 ms/call, recorded in every such
  envelope's `config.concurrent_ramp_s`) — without it, N=10's all-at-once call start was measured
  to overwhelm the single-process dev SFU's own connection-setup pipeline
  (`PublishTrackError: ... track publication timed out`) well below any steady-state capacity
  question; with the ramp, N=10 completes (see the table) rather than crashing outright.

### Sweep table

| Path | N | Status | one-way p50 | p95 | RTP loss | burst loss | jitter p95 | gateway CPU p95 | SFU CPU p95 | Target met | Envelope |
|:--|--:|:--|--:|--:|--:|--:|--:|--:|--:|:--|:--|
| `sip-loopback` | 1 | OK | 0.22 ms | 0.35 ms | 0 % | 0 % | 0.25 ms | 5.0 % | — | **met** | `…T161828925Z` |
| `sip-loopback` | 5 | OK | 0.21 ms | 0.32 ms | 0 % | 0 % | 0.45 ms | 10.0 % | — | **met** | `…T161931133Z` |
| `sip-loopback` | 10 | OK | 0.13 ms | 0.23 ms | 0 % | 0 % | 0.37 ms | 10.0 % | — | **met** | `…T162033378Z` |
| `sip-loopback` | 20 | OK | 0.17 ms | 0.34 ms | 0 % | 0 % | 0.74 ms | 14.9 % | — | **met** | `…T162135609Z` |
| `sip-loopback` | **40** | OK | 0.16 ms | 0.36 ms | 0 % | 0 % | 0.56 ms | 25.0 % | — | **met** | `…T162254931Z` |
| `sip-livekit` | **1** | OK | 95.8 ms | **108.6 ms** | 0 % | 0 % | 0.31 ms | 59.8 % | 5.0 % | **met** | `…T162420139Z` |
| `sip-livekit` | 5 | OK | 1298.7 ms | 1319.2 ms | 0 % | 0 % | 3.04 ms | 169.2 % | 10.0 % | not met (delay) | `…T163134898Z` |
| `sip-livekit` | 10 | PARTIAL | 583.6 ms | 1856.9 ms | 0 % | 47.7 % | 8.61 ms | 204.5 % | 19.9 % | not met (delay+loss) | `…T164145845Z` |
| `sip-livekit` | 20 | **NOT_RUN** | — | — | — | — | — | — | — | — | none — see below |
| `sip-livekit` | 40 | **NOT_RUN** | — | — | — | — | — | — | — | — | none — see below |

**`sip-livekit` N=20 / N=40: NOT_RUN, reason "the in-process harness did not complete a full run
within a practical time bound".** Two attempts at N=20 (100 s and 250 s wall-clock `timeout`, well
past the ~61 s a completed run takes at every smaller N) neither raised nor finished; nothing was
written by `write_result` (no envelope exists to write a number from — SPEC §27), and every port
was clean afterward (the process was killed cleanly). N=40 was not attempted: N=20 already
exceeded a practical bound under the same harness, so a larger N would not add information. This
is a genuine limitation of **this benchmark's own single-process architecture** — see below —, not
evidence about the product's real (multi-process) deployment.

**The highest N with p95 ≤ 150 ms and loss < 1 % (80 §80.8.3's own framing):**

- **`sip-loopback` (gateway-only): N = 40**, the largest N tested — the real SIP/RTP gateway
  process itself shows no sign of a ceiling at any tested N (delay stays sub-millisecond, 0 % RTP
  loss throughout, CPU rises only to ~25 % of one core at N=40).
- **`sip-livekit` (the full path — SIP leg + SFU, ТЗ ¶161's own path): N = 1.** N=5 already misses
  the delay target by roughly 9x (p95 1319 ms) with zero RTP-level loss; N=10 additionally shows
  real burst-detection loss (47.7 %). REQ-2138's «≥ 20 simultaneous sessions» is **not** met by
  this measurement on `sip-livekit`.

**Why `sip-livekit` degrades where `sip-loopback` does not — read before citing N=1 as a capacity
ceiling.** `sip-loopback`'s isolated gateway subprocess proves the SIP/RTP gateway itself is not
the bottleneck (0 % loss, sub-ms delay, low CPU up to N=40). `sip-livekit`'s own SFU CPU stays low
too (≤ 20 % of one core through N=10) — the dev LiveKit server is not saturated either. What *is*
saturated, per `gateway_cpu_percent` climbing past 200 % of one core by N=10, is **this benchmark's
own harness process**: it hosts the gateway, N SIP UAs' 20 ms real-time send/receive loops, and 2N
LiveKit SDK room connections (each with its own native FFI thread pool) all in one Python
interpreter — an artefact of how this benchmark measures `sip-livekit` (in-process, mirroring the
single-call path), not of the deployed `sip-gateway`/`voice-agent` processes, which run separately
in `infra/docker-compose.yml`. **REQ-2138/REQ-2139's real answer therefore needs a multi-process
load generator (N independent OS processes or hosts each driving one call) that this epic's
`benchmarks/benchmark_voip.py` does not build** — recorded honestly as a gap in `docs/AUDIT.md`
rather than papered over with a rearchitected harness this epic's brief does not scope.

## Not measured here

The AI-in-the-loop concurrency bound (LLM/TTS/ASR per call, VRAM on one 8 GB card) is a different,
unmeasured number — E19's own scope, not this file's (`vram.md`); `docs/AUDIT.md` records it as
UNMEASURED against REQ-2138 explicitly. `sip-livekit` concurrency above N=10 is `NOT_RUN` for the
harness reason above, not because it was skipped.

## Reproduce

```
uv run python benchmarks/benchmark_voip.py --path sip-loopback           # no server needed
docker compose -f infra/docker-compose.yml up -d --no-deps livekit       # dev SFU on 7880-7882
SIM_LIVEKIT_URL=ws://127.0.0.1:7880 SIM_LIVEKIT_API_KEY=... SIM_LIVEKIT_API_SECRET=... \
  uv run python benchmarks/benchmark_voip.py --path sip-livekit
SIM_LIVEKIT_URL=... uv run python benchmarks/benchmark_voip.py --path livekit-only

# I3 E6f — the load sweep (repeat --concurrent N for N in 1 5 10 20 40):
uv run python benchmarks/benchmark_voip.py --path sip-loopback --concurrent 40   # no server needed
SIM_LIVEKIT_URL=ws://127.0.0.1:7880 SIM_LIVEKIT_API_KEY=... SIM_LIVEKIT_API_SECRET=... \
  uv run python benchmarks/benchmark_voip.py --path sip-livekit --concurrent 10

docker compose -f infra/docker-compose.yml rm -sf livekit
```

Without the SDK, the key/secret or a server, both LiveKit paths write `status: NOT_RUN` with the
reason and no number.
