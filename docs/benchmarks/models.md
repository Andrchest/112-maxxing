# `docs/benchmarks/models.md` — local model inventory (R9 of the E19-F task brief)

Every model file actually present on this machine as of **2026-09-22**, whether under the repo's
gitignored `models/` directory or under the owner's read-only `~/models/` — file, size, sha256
(computed on this checkout, this date), source repo, pinned revision (where one exists), licence,
who fetched it and when. See `docs/hld/60-inference-ops.md` §11 for the profile-facing
cross-reference (`asr.model_path`/`vad.model_path`/`llm.model_path` → this table) and
`models/README.md` for the per-directory detail this table summarises. `docs/benchmarks/results/
llama-server-b11065-help.txt` (§2 below) is the pinned llama.cpp CUDA image's own verification, not
a model file, and is recorded separately.

Sha256 of the repo's `models/` files was computed fresh by this task (`sha256sum`, 2026-09-22);
provenance (source repo + revision) for GigaAM, Qwen3-4B, Piper and Qwen3-TTS came from each
directory's own `.cache/huggingface/download/*.metadata` (first line = resolved commit, second =
sha256 the download itself verified against) — not re-guessed. GigaAM's upstream repo id was not
recorded anywhere in the checkout; it was found by matching both pinned commit hashes against the
HuggingFace API (`ai-sage/GigaAM-v3`, confirmed: both commits exist in that repo and each revision's
own file listing matches which of the two local checkpoints needs `tokenizer.model` — see §1 below).

## 1. `models/` (repo root, gitignored)

| File | Size (bytes) | sha256 | Source repo | Pinned revision | Licence | Fetched by / when |
|:--|--:|:--|:--|:--|:--|:--|
| `silero-vad/silero_vad.onnx` | 2,327,524 | `2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f` | `github.com/snakers4/silero-vad` | tag `v5.1.2` (pinned in the Makefile, not "main"/"latest") | MIT | `make models-silero`, E12, 2026-09-21 |
| `gigaam-v3-e2e_ctc/pytorch_model.bin` | 442,405,251 | `9801f83ef3979779982c4f83ec1c234d7571e8c1a5aa2bfc0b09ceb97a16cd75` | `huggingface.co/ai-sage/GigaAM-v3` (found via HF API commit match — see header note; not recorded anywhere in the checkout itself) | `cec030b4c4f35d928e4a9044a3bdb29ebd499fac` (from `.cache/huggingface/download/pytorch_model.bin.metadata`, first line) | MIT (checkpoint's own `README.md`) | owner, by hand, before this task started (`models/README.md`); local `.cache` shows the underlying HF fetch happened 2026-09-20T00:43 UTC (`.metadata` mtime `1789995816.8`) |
| `gigaam-v3-e2e_ctc/tokenizer.model` | 240,941 | `0b9a1960898fbfdf5424ab852ea17445eb3da960fba23e977ff100eb0054fbc8` | same repo/commit as above | `cec030b4c4f35d928e4a9044a3bdb29ebd499fac` | MIT | same as above |
| `gigaam-v3-ctc/pytorch_model.bin` | 441,719,299 | `64d9c925df4bfd57e19f7b26d001106f9c5a35bd088a71c5bde071bf92c4a559` | `huggingface.co/ai-sage/GigaAM-v3` | `15ef3b5a88da78f93134b3cb7f015c70aefa8946` (this revision's own file listing has NO `tokenizer.model`, matching the local directory exactly — the CTC head uses the char vocabulary embedded in `config.json` instead) | MIT | owner, by hand, before this task started |
| `Qwen3-4B-Q4_K_M.gguf` | 2,497,280,256 | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | `huggingface.co/Qwen/Qwen3-4B-GGUF` | HF repo `main` at fetch time; file identity is this sha256 (matches the repo's own LFS pointer, per `.cache/.../Qwen3-4B-Q4_K_M.gguf.metadata`, commit `bc640142c66e1fdd12af0bd68f40445458f3869b`) | Apache-2.0 | `make models-llm`, E13-B1, 2026-09-21 |
| `llm/Qwen3.5-2B-Q4_K_M.gguf` | 1,280,835,840 | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` | `huggingface.co/unsloth/Qwen3.5-2B-GGUF` (§3: no official `Qwen/Qwen3.5-*-GGUF` repo exists) | `f6d5376be1edb4d416d56da11e5397a961aca8ae` (pinned in the Makefile) | see the repo's own licence file (base model `Qwen/Qwen3.5-2B`, Apache-2.0) | `make models-llm-qwen35`, **this task (E19-F), 2026-09-22** — sha256-**identical** to the owner's `~/models/Qwen3.5-2B/Qwen3.5-2B-Q4_K_M.gguf` (§3), confirming that file's own provenance |
| `piper/ru_RU-irina-medium.onnx` | 63,201,294 | `8ff38212d23da300bbe3705c645e6e5b9475f0bfde01558eb17813e22acaaaaa` | `huggingface.co/rhasspy/piper-voices`, path `ru/ru_RU/irina/medium/` | HF repo `main` at fetch time (no per-file revision pin; identity is this sha256) | MIT | `make models-piper`, E14-C, 2026-09-21 |
| `piper/ru_RU-irina-medium.onnx.json` | 4,765 | `c2ec28bb38e2b59e93b959b3e40348c1afebbd272f30fed5d41205d08e98a9d7` | same as above | same as above | MIT | E14-C, 2026-09-21 |
| `qwen3-tts/Qwen3-TTS-12Hz-0.6B-CustomVoice/model.safetensors` | 1,811,626,576 | `bc3c7e785eb961179c25450d1acff03f839e0002f2f3a5aeb67b5735c0fa2adb` | `huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` | `85e237c12c027371202489a0ec509ded67b5e4b5` (`.metadata`; agrees across every file in the checkpoint, per `models/README.md`) | see repo's own licence file | E14-D, 2026-09-21 |
| `qwen3-tts/Qwen3-TTS-Tokenizer-12Hz/model.safetensors` | 682,293,092 | `836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258` | `huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz` | `7dd38ad4e9bad454aae9cd937d0cd577604fe229` | see repo's own licence file | E14-B, 2026-09-21 |
| `qwen3-tts/Qwen3-TTS-12Hz-1.7B-CustomVoice/model.safetensors` | 3,833,402,552 | `38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137` | `huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` | `0c0e3051f131929182e2c023b9537f8b1c68adfe` (`.metadata`; agrees across the checkpoint) | see repo's own licence file | `QWEN3_TTS_VARIANT=1.7B make models-tts-qwen3`, **E19-D3, 2026-09-22** — the owner's GPU process (PID 1082982) had been stopped by this point, freeing ~6.2 GB, which is why this download and the real DEV_3060TI VRAM/TTS runs below became possible |
| `warmup/warmup_ru.wav` | 111,148 | (not pinned — synthesized output, not a fetched model; see §4) | n/a — built locally by `benchmarks/data/warmup/build_warmup.py` from `piper/ru_RU-irina-medium.onnx` | n/a | inherits the Piper voice's MIT licence | **this task (E19-F), 2026-09-22**, `make models-warmup` |

**Not on disk / not attempted (honest, per R4/R9):**

| Model | Repo | Pinned revision | Status |
|:--|:--|:--|:--|
| Qwen3-8B Q4_K_M | `Qwen/Qwen3-8B-GGUF` | `7c41481f57cb95916b40956ab2f0b139b296d974` (HF API, 2026-09-22; `Q4_K_M` file sha256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`, 5,027,783,488 bytes) | NOT executed (this task, R9) — `make models-llm-qwen3-8b` is defined and pinned but not run: no Qwen3-8B GGUF and no 3080 Ti exist on this machine |
| Qwen3.5-0.8B / Qwen3.5-4B (repo copies) | `unsloth/Qwen3.5-0.8B-GGUF` / `unsloth/Qwen3.5-4B-GGUF` | `6ab461498e2023f6e3c1baea90a8f0fe38ab64d0` / `e87f176479d0855a907a41277aca2f8ee7a09523` | not fetched into `models/llm/` by this task (only the profile-default 2B, per R9 step 2) — pinned and downloadable via `make models-llm-qwen35 QWEN35_LLM_SIZE=0.8B\|4B` |

## 2. Owner's `~/models/` (READ-ONLY — read, nothing copied into it)

| File | Size (bytes) | sha256 | Matches which HF repo/revision (§3) |
|:--|--:|:--|:--|
| `Qwen3.5-0.8B/Qwen3.5-0.8B-Q4_K_M.gguf` | 532,517,120 | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` | `unsloth/Qwen3.5-0.8B-GGUF@6ab461498e2023f6e3c1baea90a8f0fe38ab64d0` (byte-identical) |
| `Qwen3.5-2B/Qwen3.5-2B-Q4_K_M.gguf` | 1,280,835,840 | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` | `unsloth/Qwen3.5-2B-GGUF@f6d5376be1edb4d416d56da11e5397a961aca8ae` (byte-identical) |
| `Qwen3.5-4B/Qwen3.5-4B-Q4_K_M.gguf` | 2,740,937,888 | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` | `unsloth/Qwen3.5-4B-GGUF@e87f176479d0855a907a41277aca2f8ee7a09523` (byte-identical) |

None of these three directories carries a `.cache/huggingface` provenance trail (unlike every
`models/` entry in §1) — no local record of which repo/revision the owner downloaded them from.
**Provenance below is resolved, not "unrecorded"**: this task queried the HuggingFace API for every
plausible `Qwen3.5-<size>-GGUF` repo, found that **no official `Qwen/Qwen3.5-<size>-GGUF` repo
exists** (§3), then compared file size and sha256 against the two most likely community quantizers
(`bartowski`, `unsloth`) — all three owner files are byte-for-byte identical to
`unsloth/Qwen3.5-<size>-GGUF`'s `Q4_K_M` file at that repo's HEAD commit on 2026-09-22 (recorded
above as the pinned revision, since "the repo's HEAD today" is itself a moving target — the Makefile
pins these exact commits, §3). Owner downloaded, date unrecorded (files' own mtimes: 2026-08-22/23).

## 3. Why `unsloth/*`, not an "official" Qwen GGUF repo (this task's own resolution, 2026-09-22)

Fetched by `make models-llm-qwen35` (Makefile `models-*` block). Unlike `Qwen3-4B-GGUF` (Qwen's own
org ships a `Qwen/Qwen3-4B-GGUF` repo), **Qwen does not publish a `Qwen/Qwen3.5-<size>-GGUF` repo at
all**: `Qwen/Qwen3.5-{0.8B,2B,4B}` on HF are `safetensors`-only, `pipeline_tag: image-text-to-text`
(Qwen3.5 shipped as a multimodal-capable base checkpoint); querying
`https://huggingface.co/api/models/Qwen/Qwen3.5-<size>-GGUF` returns HTTP 401 with the same
`{"error":"Invalid username or password."}` body a **confirmed-nonexistent** repo returns (verified
against a random nonsense repo id, same response) — not a private/gated repo, a repo that does not
exist. `unsloth/Qwen3.5-<size>-GGUF` is the community quantizer whose `Q4_K_M` file is
byte-identical to what the owner already had (§2), which is the strongest provenance evidence
available (identity, not a guess) — `bartowski/Qwen_Qwen3.5-2B-GGUF`'s `Q4_K_M` was checked too and
is a **different** file (1,396,198,496 bytes vs. the owner's 1,280,835,840), ruling it out.

| Size | Repo | Revision (pinned) | `Q4_K_M` sha256 |
|:--|:--|:--|:--|
| 0.8B | `unsloth/Qwen3.5-0.8B-GGUF` | `6ab461498e2023f6e3c1baea90a8f0fe38ab64d0` | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` |
| 2B (profile default) | `unsloth/Qwen3.5-2B-GGUF` | `f6d5376be1edb4d416d56da11e5397a961aca8ae` | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` |
| 4B | `unsloth/Qwen3.5-4B-GGUF` | `e87f176479d0855a907a41277aca2f8ee7a09523` | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` |

## 4. `warmup/warmup_ru.wav`

Built by `benchmarks/data/warmup/build_warmup.py` (committed script) from the already-fetched Piper
voice above; text `«Проверка готовности перед началом смены.»`, 2.5 s, 16-bit PCM mono (Piper's
native sample rate, 22050 Hz). **Not byte-for-byte reproducible** across re-runs of the build script
(measured by this task: two runs differ in both duration and sha256 — Piper/VITS's noise-scale input
is generated *inside* the ONNX graph by a `RandomNormal` op the public `piper-tts` API cannot seed;
see the script's own docstring). The committed file is therefore a one-time build output, not a
value future CI runs are expected to reproduce exactly — its duration budget (≤ 3 s, enforced by the
script) and validity as real Piper audio are what matter for its purpose (ASR warm-up, HLD §4.2).

## 5. Final host `models/` layout (`make models-layout`, idempotent, symlinks only)

```
models/llm/Qwen3-4B-Q4_K_M.gguf        -> ../Qwen3-4B-Q4_K_M.gguf          (symlink)
models/llm/Qwen3.5-2B-Q4_K_M.gguf      -> real file (models-llm-qwen35 downloads directly here)
models/asr/gigaam-v3-e2e-ctc           -> ../gigaam-v3-e2e_ctc             (symlink; hyphenated to
                                           match the profile path, owner's dir keeps its underscore
                                           name, never renamed)
models/asr/gigaam-v3-ctc               -> ../gigaam-v3-ctc                 (symlink)
models/tts/piper                       -> ../piper                        (symlink)
models/tts/qwen3-tts                   -> ../qwen3-tts                    (symlink)
models/vad/silero_vad.onnx             -> ../silero-vad/silero_vad.onnx    (symlink)
models/warmup/warmup_ru.wav            -> real file (make models-warmup cp's it here, not a symlink)
```

`infra/docker-compose.yml`'s mount stays `../models:/models` (unchanged) — every profile YAML's
`/models/<rest>` path (`llm.model_path`, `asr.model_path`, `tts.model_path`/`fallback_model_path`,
`vad.model_path`, `warmup.asr_sample_path`) now resolves against this layout without any profile
edit. `benchmarks/_common.py`'s `resolve_model_path` (E19-A) maps `/models/<rest>` →
`<models_root>/<rest>` directly against this same layout, with the legacy top-level names (e.g.
`models/Qwen3-4B-Q4_K_M.gguf`) kept as a documented fallback.
