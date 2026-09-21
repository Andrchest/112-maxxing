# `tts_qwen3` — the Qwen3-TTS GPU worker

A standalone FastAPI process, loopback-only, in its **own** venv
(`workers/tts_qwen3/.venv`, created by `scripts/setup_tts_qwen3.sh`). It is not a member of the
root `sim112-workspace` (`pyproject.toml`'s `[tool.uv.workspace]` lists `backend`,
`workers/voice_agent`, `benchmarks` only — this package by name), it is never imported by
`backend` or `workers/voice_agent`, and `backend/tools/check_imports.py` enforces that.

## Why a separate process

`qwen-tts==0.1.1` (the owner's evaluated, GPU-verified package — OWNER DECISION, docs/hld/
90-tbd-epics.md epic E14) pins `torch==2.14.0`. The backend's `asr-gigaam` extra caps
`torch>=2.6,<2.9` for GigaAM's ASR checkpoint. One venv cannot satisfy both floors at once, so
this worker gets its own venv and is dialled over loopback HTTP by
`backend/app/inference/tts/qwen3_tts.py::Qwen3TTS`, an `httpx` client that implements the
`TTSProvider` port (`docs/hld/50-voice-pipeline.md` §2.4) — the same "separate process, HTTP
client" shape the owner's own reference implementation uses
(`/tmp/teamwork-112-maxxing/reports/e14-recon.md` §1.1, §6 item 3).

## Model

`SIM_TTS_QWEN3_MODEL` (`tts_qwen3.server.MODEL_VARIANTS`) picks the checkpoint — a config choice,
never a code edit (E14-D):

| `SIM_TTS_QWEN3_MODEL` | Repo | Pinned revision |
|:--|:--|:--|
| `1.7B` (**default** — the owner's evaluated model, unchanged, OWNER DECISION E14) | `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | `0c0e3051f131929182e2c023b9537f8b1c68adfe` |
| `0.6B` (measured alternative, E14-D — see `docs/hld/60-inference-ops.md` §10 open item 6 for the real run's numbers) | `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | `85e237c12c027371202489a0ec509ded67b5e4b5` |

An unrecognised value raises `UnknownModelVariantError` when the app is built (i.e. at
`python -m tts_qwen3` import time) — the process refuses to start rather than silently falling
back to the default or failing deep inside a request. Each variant's checkpoint lives in its own
subdirectory under `SIM_TTS_QWEN3_MODEL_DIR` (default `models/qwen3-tts/`,
`Qwen3-TTS-12Hz-<variant>-CustomVoice/`) — `create_app()` joins them; `/health`'s `model`/`revision`
report whichever variant actually loaded, not a hard-coded constant.

- tokenizer (shared by both variants) `Qwen/Qwen3-TTS-Tokenizer-12Hz` @ revision
  `7dd38ad4e9bad454aae9cd937d0cd577604fe229`
- 4 vendor speakers only: `Serena`, `Ryan`, `Vivian`, `Aiden`.
- Output: raw PCM s16le mono **24000 Hz**.
- Generation is **whole-utterance** (`generate_custom_voice()` returns a complete waveform, no
  native streaming/cancellation — recon §1.1). The mandatory mitigation lives on the client side
  (`app.application.voice`'s sentence chunker, owned by E14-A): each `/synthesize` call gets one
  sentence/clause, never a whole caller turn, so `TtsStream.cancel()` has a bounded unit to stop
  after. Measured true (both variants): `docs/hld/60-inference-ops.md` §10's Piper table (1.7B
  still NOT_RUN on this machine) and open item 6 (0.6B, real run, E14-D).

## Running it

```
make deps-tts-qwen3     # creates workers/tts_qwen3/.venv, installs the pinned deps
make models-tts-qwen3   # downloads QWEN3_TTS_VARIANT's (default 1.7B) pinned model+tokenizer
                         # revisions into models/qwen3-tts/ (requires >= 12 GB free disk for 1.7B,
                         # >= 8 GB for 0.6B; NOT_RUN otherwise — ~4.3 GB / ~2.4 GB payload)
make run-tts-qwen3       # starts the worker on 127.0.0.1:${SIM_TTS_QWEN3_PORT:-8112},
                         # SIM_TTS_QWEN3_MODEL=$(QWEN3_TTS_VARIANT) (default 1.7B)
```

`QWEN3_TTS_VARIANT=0.6B make run-tts-qwen3` (or `QWEN3_TTS_VARIANT=0.6B make models-tts-qwen3`)
selects the 0.6B checkpoint for either target; both dirs are already present in this checkout (no
download needed).

Never port 8012 (that belongs to the owner's own experiment) or 8016 (the owner's currently
resident Higgs-TTS process, PID checked at `docs/hld/60-inference-ops.md`'s machine-rules note) —
the default here is **8112**.

## Endpoints

- `GET /health` -> `{status, model, revision, device, loaded}` — `model`/`revision` are the
  *actually configured* variant's (E14-D), not a fixed constant.
- `POST /warm_up` -> loads the model (idempotent; also triggered lazily by the first `/synthesize`)
- `POST /synthesize {text, speaker, language, instruct, request_id}` -> `audio/L16` raw PCM body,
  headers `X-Sample-Rate`, `X-Audio-Ms`, `X-Gen-Ms`. A request whose client disconnected before it
  got the inference lock is dropped, not generated. Every failure is `503` with a stable JSON body
  that never echoes exception text (mirrors the owner's own worker's failure contract, recon §1.1).

## Tests

`tests/test_server.py` drives the FastAPI app with a **fake** model factory — no `torch`/
`qwen-tts` import anywhere in the test process. It runs in this package's own venv
(`make test-tts-qwen3`). A second, narrower copy of the same request/response-shape assertions
also runs under the main backend gate — see
`backend/tests/unit/inference/tts/test_qwen3_worker_shape.py`'s module docstring for why that is
possible (FastAPI is already a plain `sim-backend` dependency, so this module's `server.py` — which
does no heavy import at module scope — is importable there too, via a `sys.path` insert, without
installing this package's `qwen-tts`/`torch==2.14.0` pins into the main venv).

E14-D added variant-resolution tests to `tests/test_server.py`: default (1.7B) resolves its own
subdirectory, `0.6B` resolves its own repo/revision/subdirectory (both via the `variant=` kwarg and
via `SIM_TTS_QWEN3_MODEL`), an unknown value raises `UnknownModelVariantError` (kwarg and env var),
and `/health` reports the resolved variant's `model`/`revision` (same 5-key response shape as
before — no new key, so `test_qwen3_worker_shape.py`'s exact-key-set assertion is unaffected).
