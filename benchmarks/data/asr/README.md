# `benchmarks/data/asr/` — ASR benchmark corpus (SPEC §19, §40; HLD `60-inference-ops.md` §7.1)

Committed, deterministic, ≤ 12 MB of WAV (`du -sh benchmarks/data/asr` → 12M / 11,889,746 bytes
measured 2026-09-22). Built by `build_corpus.py` from `texts.jsonl`; `manifest.jsonl` is the
contract `benchmark_asr.py` reads (`{id, path, reference, category, condition, duration_ms,
source}`, `path` relative to this directory).

## Provenance

**36 texts × 2 conditions (72 items) + 1 human recording = 73 manifest rows.**

- **Synthesized items** (`source: "piper:ru_RU-irina-medium"`, 72 rows): `texts.jsonl` (36
  hand-written dispatcher-style Russian sentences, ≥ 6 per `category`) synthesized on CPU with
  `piper-tts` (`ru_RU-irina-medium.onnx`) by `build_corpus.py`, using the raw `piper.PiperVoice`
  API directly — the same entry point `benchmarks/data/warmup/build_warmup.py` (E19-F) uses, not
  the product's async `PiperTTS` adapter (`backend/app/inference/tts/piper_tts.py`), which exists
  to be driven from the voice pipeline's own event loop and would add nothing here. 16 kHz mono
  16-bit PCM WAV, written under `clean/<category>/<id>.wav`.
- **`NOISY`** twins (36 of the 72): the matching `clean/` waveform mixed with seeded Gaussian noise
  at **10 dB SNR** (`--snr-db`, `build_corpus.py`'s default), computed from *that item's own* RMS
  (`noise_rms = signal_rms / 10**(snr_db/20)`), `numpy.random.default_rng(seed=20260922)`. Written
  under `noisy/<category>/<id>.wav`.
- **One human recording** (`source: "human:gigaam-sample"`, id `long_human_01`,
  `clean/long/long_human_01.wav`): a copy of `backend/tests/models/assets/ru_sample.wav` — GigaAM's
  own published example recording (Pushkin, «У лукоморья дуб зелёный»), MIT licence, sha256 and
  full provenance in that directory's own `README.md`. `reference` is that project's own published
  transcript (`colab_example.ipynb`), copied verbatim. No synthesized `NOISY` twin is built for it:
  this script does not alter a licensed recording — see "adding a human recording" below for how a
  noisy human sample would be added instead.

**Determinism.** `build_corpus.py --seed N` is deterministic in everything it controls: item order,
the noise RNG, the SNR calculation. Piper's own synthesis is **not** bit-reproducible across runs —
`build_warmup.py`'s docstring found VITS's noise-scale RNG lives inside the ONNX graph itself, not
on a Python-seedable path, so `numpy.random.seed()`/`default_rng()` cannot pin it. Re-running
`build_corpus.py` therefore reproduces the same corpus *content* (same texts, same categories, same
SNR) but not necessarily byte-identical `clean/` WAVs; the committed files here are the ones
actually measured against in `docs/benchmarks/asr.md`, not something a CI re-run is expected to
reproduce exactly (same caveat, same reason, as `benchmarks/data/warmup/`).

## The TTS→ASR round-trip caveat

Every synthesized item in this corpus is Piper's own pronunciation of a written sentence, not a
recording of a human speaker. **A WER measured on `piper:*` items measures GigaAM against Piper's
pronunciation of the reference text, not against human speech variation** — accent, disfluency,
breath noise, microphone/room acoustics, speaking-rate variation, none of which a synthesized
corpus can supply by construction. `docs/benchmarks/asr.md` reports WER **per `source`** for
exactly this reason: the `piper:*` aggregate and the one `human:gigaam-sample` row are never
blended into a single number that would obscure which kind of speech was measured. Read the
`piper:*` rows as "does GigaAM transcribe clean synthetic Russian dispatcher speech correctly" and
the `human:*` row as the (single, small) cross-check against a real voice.

## Categories

`category ∈ {SHORT, MEDIUM, LONG, ADDRESS, NUMBER, TERMINOLOGY}` (HLD §7.1). SHORT = ≤ 4 words,
MEDIUM = 5–12 words, LONG = 13+ words and ≥ 6 s of synthesized audio (all six LONG items measure
7.6–9.0 s; the human item is 11.3 s). ADDRESS and NUMBER reuse the demo scenario's own vocabulary
(`scenarios/examples/apartment-fire/v1.yaml`: Смоленск, улица Николаева, дом 27, подъезд 3, этаж 4,
квартира 45, phone `+79101234567`, victim age 78, `floor_count` 9, `total_inside` 1) so the corpus
exercises the exact address/number shapes a trainee will actually hear. TERMINOLOGY draws on SPEC
§40's own list (пожар, задымление, возгорание, пострадавший, без сознания, ДТП, скорая, МЧС,
эвакуация).

`condition ∈ {CLEAN, NOISY}`.

## Directory layout

```
benchmarks/data/asr/
  texts.jsonl        # 36 {id, category, text} rows — the committed, human-edited source
  build_corpus.py    # deterministic builder (this README's "Provenance")
  manifest.jsonl      # generated; the contract benchmark_asr.py reads
  README.md           # this file
  clean/{short,medium,long,address,number,terminology}/*.wav
  noisy/{short,medium,long,address,number,terminology}/*.wav
```

## Adding a human recording

Drop a 16 kHz mono 16-bit PCM WAV anywhere under this directory (a natural spot: `clean/<category
matching its content>/<new-id>.wav`, or a new `noisy/` twin recorded/mixed the same way), then add
one row to `manifest.jsonl` by hand: `{"id": "<new-id>", "path": "<relative path>", "reference":
"<verbatim transcript>", "category": "<one of the six>", "condition": "CLEAN|NOISY", "duration_ms":
<wav length>, "source": "human:<who>"}`. State the recording's licence/consent in this README next
to this section. `build_corpus.py` never touches a `source` starting with `human:` other than the
one copy step above, so a hand-added row survives a re-run of the script (it only rewrites the
`piper:*` rows it itself produced) — **caveat:** re-running `build_corpus.py` overwrites
`manifest.jsonl` wholesale from `texts.jsonl` plus the one hard-coded human copy, so a hand-added
row must be re-appended after a re-run, or `texts.jsonl`/`build_corpus.py` extended to read
`human_samples.jsonl` if this ever needs to scale past one file.

## Regenerating

```
uv run python benchmarks/data/asr/build_corpus.py
```

Requires `models/piper/ru_RU-irina-medium.onnx` (+ `.onnx.json`) on disk — `make models-piper`.
