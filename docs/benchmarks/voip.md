# VoIP one-way delay (ТЗ ¶161, REQ-2139; HLD `80-telephony.md` §80.8.3, §80.11) — I3 E6a

Machine: `andreipc-B660M-DS3H-DDR4` (the dev box). Date: **2026-09-24**. Script:
`benchmarks/benchmark_voip.py`. GPU: not used (no model runs on any path). Code: branch
`feat/i3-requirements-alignment` at `366a2e5` **plus the uncommitted E6a working tree** (the
envelopes' `git_sha` is the HEAD the tree sat on). Raw envelopes: `docs/benchmarks/results/voip-*`.

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

## Not measured here

The concurrency sweep (`--concurrent N`, 1/5/10/20/40, gateway/SFU CPU) is epic **E6f**; this file
has no number for it. The AI-in-the-loop concurrency bound (LLM/TTS on one 8 GB card) is a
different, unmeasured number (`vram.md`).

## Reproduce

```
uv run python benchmarks/benchmark_voip.py --path sip-loopback           # no server needed
docker compose -f infra/docker-compose.yml up -d --no-deps livekit       # dev SFU on 7880-7882
SIM_LIVEKIT_URL=ws://127.0.0.1:7880 SIM_LIVEKIT_API_KEY=... SIM_LIVEKIT_API_SECRET=... \
  uv run python benchmarks/benchmark_voip.py --path sip-livekit
SIM_LIVEKIT_URL=... uv run python benchmarks/benchmark_voip.py --path livekit-only
docker compose -f infra/docker-compose.yml rm -sf livekit
```

Without the SDK, the key/secret or a server, both LiveKit paths write `status: NOT_RUN` with the
reason and no number.
