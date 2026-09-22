# LLM benchmark — real measurements (E19-C / E19-C2)

SPEC §20-§22, §26, §27, §35, §40, §43, §44 · HLD `60-inference-ops.md` §7.2 · epic E19 rulings R1,
R4, R6, R8, R13.

**Machine and date.** NVIDIA GeForce RTX 3060 Ti, 8192 MiB total, driver 595.84, CUDA host build of
`llama-server` at `/home/andreipc/src/llama.cpp/build/bin/llama-server` (`0.2.0-dev`, commit
`2115b73`); Linux, Python 3.12 via `uv`. **2026-09-22**, 05:27-05:34 UTC. The card is **shared**:
the owner's process (PID 1082982) held 4638 MiB throughout, leaving **3196 MiB free before every
single run** (`nvidia-smi --query-gpu=memory.free` recorded before and after each; every reading
identical). `nvml_mode=pynvml` on every OK run.

Every number below is read out of a committed result JSON in [`results/`](results/); no number in
this file was typed by hand (SPEC §27: "do not fake or hard-code benchmark values"). The files are
named `e19c-llm-<model>-<profile>-<timestamp>.{json,csv}`.

> **History.** An earlier pass (2026-09-22, 04:58-05:14 UTC) measured the same corpus **before**
> E19-C2's two-boundary fix for the degenerate caller utterance (§3). Those numbers are superseded
> and their result files have been removed, but the comparison is the evidence that the fix works
> and is quoted throughout §3. In one line: before the fix, **13-27 of 46** dialogue turns per
> Qwen3.5 model were a bare `}`; after it, **0 of 46** on every model.

## 1. What was run

```bash
export SIM_LLAMA_SERVER_BIN=/home/andreipc/src/llama.cpp/build/bin/llama-server
uv run python benchmarks/benchmark_llm.py --provider real --suite all --runs 1 \
    --model-path <gguf> --parallel <2|1> --tag <label> --out benchmarks/results/e19c-llm-v3/<label>
# all of it inside: flock -w 10800 /tmp/teamwork-112-maxxing/gpu.lock bash <run script>
```

Per run: 37 interpreter cases + 46 dialogue turns (13 multi-turn scripts) + 2 explanation calls =
**85 measured samples**, preceded by **2 warm-up completions excluded from every sample** (their
latencies are in the envelope's `notes`).

The call parameters are the **product's own** (`Settings` defaults, not the dataclass defaults):
interpreter `max_tokens=138`, `timeout_ms=2500`, grammar on; generator `max_tokens=80`,
`timeout_ms=3000`, `temperature=0.7`, `top_p=0.9`, grammar on; explanation `max_tokens=400`,
`temperature=0.2`, `timeout_ms=8000`.

**The dialogue suite runs the product's `ValidatorConfig`** (E19-C2, R13):
`max_chars=400`, `max_sentences=3`, `max_response_tokens=80` and the **default**
`small_count_allowlist={"0","1","2","3"}` — the shipped gate, recorded in the envelope's
`config.validator`. The §43 suite's `STRICT` config, which *empties* that allowlist, belongs to the
adversarial forbidden-fact sub-suite and is not what any deployment runs; using it for the whole
dialogue suite (as the first pass did) counted «3» (подъезд) and «1» (один человек) as `NEW_NUMBER`.
The forbidden-value scan is unaffected either way: `forbidden_values()`/`leaked_values()` take no
`ValidatorConfig` at all, so §43 keeps its own strictness where it belongs.

| Model | GGUF | slots | offload | server peak VRAM (sampled) | status | result file |
|:--|:--|--:|:--|--:|:--|:--|
| Qwen3.5-0.8B Q4_K_M | `~/models/Qwen3.5-0.8B/…` (read-only) | 2 | GPU_FULL (999 L) | 840 MiB | OK | `…-qwen35-0.8b-p2-…-20260922T052754566Z` |
| **Qwen3.5-2B Q4_K_M** | `models/llm/Qwen3.5-2B-Q4_K_M.gguf` (E19-F's download; sha256-identical to the owner's copy) | 2 | GPU_FULL (999 L) | **1560 MiB** | OK | `…-qwen35-2b-p2-…-20260922T052828858Z` |
| Qwen3.5-4B Q4_K_M | `~/models/Qwen3.5-4B/…` (read-only) | 2 | GPU_PARTIAL (26 L) | 2816 MiB | OK | `…-qwen35-4b-p2-…-20260922T053122725Z` |
| Qwen3-4B Q4_K_M | `models/llm/Qwen3-4B-Q4_K_M.gguf` | 2 | — | — | **FAILED** (CUDA OOM at load) | `…-qwen3-4b-p2-…-20260922T053157095Z` |
| Qwen3-4B Q4_K_M | `models/llm/Qwen3-4B-Q4_K_M.gguf` | 1 | GPU_PARTIAL (32 L) | 2842 MiB | OK | `…-qwen3-4b-p1-…-20260922T053435025Z` |
| Qwen3-8B Q4_K_M | — | 2 | — | — | **NOT_RUN** | `…-qwen3-8b-notrun-…-20260922T053435285Z` |

`--parallel 2` on **Qwen3-4B** dies inside llama.cpp before serving a request, verbatim from the
result's `reason`:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 992.00 MiB on device 0: cudaMalloc failed: out of memory
alloc_tensor_range: failed to allocate CUDA0 buffer of size 1040187392
llama_init_from_model: failed to initialize the context: failed to allocate buffer for kv cache
```

This reproduces E13-B4 exactly. It is recorded as **`FAILED`** (R4): the model was launched on this
card and did not fit — a measurement outcome, and `benchmark_llm.py` exits 1 for it.
**`NOT_RUN` is reserved for "never attempted"**, which is what Qwen3-8B is: no Qwen3-8B GGUF exists
anywhere on this machine, and its 5 GB Q4_K_M could not be offloaded beside the owner's 4.6 GB
process if it did. The download target (`make models-llm-qwen3-8b`, E19-F, pinned revision) is
defined and deliberately not executed here. `--parallel 1` (half the KV cache) loads and runs, so
Qwen3-4B is measured with `config.parallel_slots: 1` as a **separate** result.

**faster-whisper** and **Chatterbox** are not LLM items; their `NOT_RUN`s live in `asr.md`/`tts.md`.

## 2. Latency and throughput

`total_latency_ms` is the whole product call (prompt build → model → parse → validate → any
regeneration), not just the model.

| Model | interpreter p50 / p95 | dialogue p50 / p95 | explanation p50 / p95 | tok/s p50 (overall) |
|:--|--:|--:|--:|--:|
| Qwen3.5-0.8B | 176.9 / 468.0 | 813.5 / 1855.8 | 580.6 / 1276.8 | 176.6 |
| **Qwen3.5-2B** | **234.8 / 316.0** | **227.7 / 871.3** | **331.0 / 954.6** | 136.3 |
| Qwen3.5-4B | 1211.4 / 2007.4 | 901.9 / 3259.6 | 2409.2 / 3783.6 | 29.2 |
| Qwen3-4B (1 slot) | 1021.8 / 1423.4 | 2475.1 / 3815.6 | 1678.5 / 4989.6 | 40.7 |

All values ms. Combined **interpret + generate p50** (R6's speed criterion, interpreter p50 +
dialogue p50):

| Model | combined p50 |
|:--|--:|
| **Qwen3.5-2B** | **462.5 ms** |
| Qwen3.5-0.8B | 990.4 ms |
| Qwen3.5-4B | 2113.3 ms |
| Qwen3-4B (1 slot) | 3496.9 ms |

**`ttft_ms` is empty by construction.** `aggregates.*.ttft_ms.n == 0` on every run and that is not a
gap in the harness: the product's LLM calls are **non-streaming**, because both the GBNF grammar
and `ResponseValidator` need the *whole* completion before a single character may be spoken — a
token streamed to the trainee before the validator saw it is exactly the boundary SPEC §24 forbids
crossing. For this chain **TTFT == total latency**, and `total_latency_ms` is the number to read.
(The one place a real first-audio time exists is `benchmark_e2e.py`'s
`CALLER_TTS_STARTED.first_audio_offset_ms`, which is TTS's first chunk, not the LLM's first token.)

### The cost of the E19-C2 grammar fix

Requiring a Cyrillic letter inside the utterance (§3) removed every degenerate generation, and it
made the models *work harder for it*: dialogue p50 went 177.5 → **227.7 ms** on the 2B (+28 %),
646.0 → **2475.1 ms** on Qwen3-4B (+283 %), and a new `SCHEMA_INVALID` term appeared in the failure
histograms (the model spends its 80-token budget on a long string and truncates before closing the
JSON). The 2B pays 50 ms for it; Qwen3-4B pays nearly two seconds. This is a real trade-off and it
does not change the ruling — the 2B is still the fastest candidate by a factor of two — but it is a
reason to watch `SCHEMA_INVALID` if the default ever moves to a 4B.

Comparison with the earlier single-purpose evals (recon §6): E13-B3 measured the 2B interpreter at
p50 221 / p95 279 ms and E13-B4 the 2B generator at p50 178 / p95 349 ms. Today's interpreter
234.8 / 316.0 reproduces that; the generator is slower for the reason just given. Peak VRAM
**1560 MiB** vs E13-B4's 1558 MiB: the same figure.

## 3. Quality: the R6 bar

R6's bar for the DEV default, mechanical: `explicit_acc ≥ 0.95` **and**
`structured_output_validity_rate ≥ 0.95` **and** `forbidden_fact_leak_rate == 0` **and**
`dialogue_consistency_rate ≥ 0.90`.

| Model | explicit_acc (all / excl. uncertain) | validity (overall) | leak | consistency (n) | never-delivered pairs | fallback rate | degenerate turns | **bar** |
|:--|--:|--:|--:|--:|--:|--:|--:|:--|
| Qwen3.5-0.8B | 0.722 / 0.706 | 0.729 | **0.0** | 0.583 (12) | 2 | 0.500 | **0/46** | FAIL (3 of 4) |
| **Qwen3.5-2B** | **1.000 / 1.000** | **0.953** | **0.0** | 0.538 (13) | 1 | 0.087 | **0/46** | FAIL (consistency only) |
| Qwen3.5-4B | 0.840 / 0.909 | 0.941 | **0.0** | 0.714 (14) | 1 | 0.109 | **0/46** | FAIL (explicit_acc, validity, consistency) |
| Qwen3-4B (1 slot) | 0.826 / 0.810 | 0.624 | **0.0** | **0.929** (14) | 0 | 0.696 | **0/46** | FAIL (explicit_acc, validity) |

Other interpreter metrics, all / excluding uncertain:

| Model | speech_act_acc | requested_exact_match |
|:--|--:|--:|
| Qwen3.5-0.8B | 0.838 / 0.906 | 0.838 / 0.875 |
| Qwen3.5-2B | 0.811 / 0.844 | 0.838 / 0.844 |
| Qwen3.5-4B | 0.973 / 1.000 | 0.919 / 0.938 |
| Qwen3-4B (1 slot) | 0.946 / 1.000 | 0.919 / 0.969 |

### The degenerate-utterance defect, and its fix (E19-C2)

The first pass found the Qwen3.5 family filling the caller grammar's `utterance` string with a bare
`}`: dialogue turns whose spoken text was ≤ 3 characters numbered **23/46 (0.8B), 13/46 (2B),
27/46 (4B)** against **1/46 for Qwen3-4B**. `ResponseValidator` accepted every one of them, because
its `EMPTY` rule only fired on an empty-after-strip string and `"}"` is not empty — so a trainee
would have heard `}`. Fixed at **both boundaries**, neither relying on the other (SPEC §44):

1. **The grammar cannot produce it.** `CallerUtterance.utterance` is now
   `Annotated[str, SpokenText()]` and `app.application.dialogue.grammar` emits `speech-string`
   for such a field — `"\"" speech-char* [а-яА-ЯёЁ] speech-char* "\""`, a JSON string that must
   carry at least one Cyrillic letter. The constraint lives on the model, so
   `build_caller_response_grammar` is still a thin wrapper over the same generator, and
   `CALLER_JSON_SCHEMA` (the `use_grammar=False` fallback) is unchanged.
2. **The validator will not speak it.** §7.1's `EMPTY` rule is now "no letter after strip" rather
   than "no characters after strip" — same failure code, no new enum member.

After the fix: **0 of 46 degenerate turns on every model**, and never-delivered repeat pairs fell
from 5 to 1 on the 2B. **Consequence to be aware of:** a letter-free answer such as «3, 45» to
"Подъезд и квартира?" is now rejected too; the caller must speak a word («Подъезд 3, квартира 45»).
That is the intended reading of "empty speech", and it is pinned by a test.

### Why consistency still fails the bar

`dialogue_consistency_rate` asks: when the same `fact_id` is requested in two turns of one script,
did the caller deliver the **same canonical value** both times (§7.2 numeral folding, exact
comparison, no model judging)? With the degenerate generations gone, the residual failures on the
2B are the model's own behaviour, not the harness's. All six of its inconsistent pairs, verbatim:

* the re-ask is **refused or deflected** — «Я не имею возможности указывать на адрес…»,
  «Соседка, я не знаю этажа, но это не так важно…»;
* the value was **never stated the first time** and only arrives on the second ask
  (`cause_probe`, `phone_readback`, `entrance_and_apartment`).

`fallback_rate` is only 0.087 on the 2B, so these are real generations, not templates. Two readings
the number still needs:

1. **Consistency is inflated by the deterministic fallback for models that reject a lot.**
   Qwen3-4B's 0.929 rides on a 0.696 fallback rate: much of what it "said" is the fallback
   template, which is consistent by construction. Always read the two columns together.
2. **A repeat pair whose value was never spoken in either turn is not counted** (it goes to
   `repeat_pairs_never_delivered`), so a model that never answers cannot score 1.0. The scripts
   deliberately include UNKNOWN facts (`incident.cause`, `incident.fire_source`,
   `hazards.gas_cylinder`) whose honest answer is "I don't know"; those pairs land there.

What the metric still cannot distinguish: "answered differently" from "answered once and then not
at all". Both score `False`. Splitting them is a proposal (§5).

### Verdict

**No model on this machine meets R6's bar**, and every failure is on accuracy or consistency —
never on safety. `forbidden_fact_leak_rate` is **0.0 on all four models**, over 46 dialogue turns
each, at the output boundary with the §43 scan (`leaked_values`, enum-RU rendering included).
SPEC §43's target is met by every model tested.

**The DEV default therefore stays `Qwen3.5-2B` and no profile file was changed** (R6/R12: only a
model that *passes* may displace the incumbent). The 2B is in any case both the fastest
(462.5 ms combined p50, less than half the next candidate) and the only model clearing three of the
four criteria. `DEV_3060TI.yaml` and `DEV_3060TI_SHARED.yaml` are untouched by E19-C.

## 4. Validator failure codes — the 2B, and the rule behind the top code

From `aggregates.by_suite.dialogue.validator_failure_codes` (46 turns), with the **product's**
`ValidatorConfig`:

| Model | codes |
|:--|:--|
| **Qwen3.5-2B** | `NEW_ADDRESS_TOKEN` 1, `NEW_NAME` 1, `NEW_NUMBER` 1, `SCHEMA_INVALID` 1 |
| Qwen3.5-0.8B | `SCHEMA_INVALID` 13, `NEW_NUMBER` 4, `NEW_ADDRESS_TOKEN` 3, `META_LANGUAGE` 3, `NEW_NAME` 2, `TOO_LONG` 1 |
| Qwen3.5-4B | `NEW_NAME` 3, `SCHEMA_INVALID` 1, `NEW_NUMBER` 1 |
| Qwen3-4B (1 slot) | `SCHEMA_INVALID` 22, `META_LANGUAGE` 10 |

**The 2B has four rejections in 46 turns, one of each code — there is no meaningful "top code" for
it any more.** Under the §43 `STRICT` config the first pass showed `NEW_NUMBER` as the top code
(4 across two passes) purely because `small_count_allowlist` was empty; with the product's
allowlist restored, `NEW_NUMBER` drops to 1. The rule behind it is
`ResponseValidator._check_numbers`, `backend/app/application/dialogue/validator.py:559-575`
(the failure is raised at the `ValidationFailure(...NEW_NUMBER...)` line): every `NumberRun` the
§7.2 normaliser finds must be a number the caller was told this turn (`permitted.numbers`) or a
member of `small_count_allowlist`. **No validator rule was loosened in E19** (R6) — `EMPTY` was
*widened*, which is the opposite direction.

The code worth an owner's attention is now `SCHEMA_INVALID` on the small and the old models
(13 on the 0.8B, 22 on Qwen3-4B): with the tightened grammar they exhaust `max_tokens=80` inside
the utterance string and truncate before closing the JSON.

## 5. Proposals (not applied)

1. **Restate a previously revealed fact on a re-ask.** The prompt builder already assembles an
   `already_revealed` block (`CallerPromptConfig.already_revealed_token_budget`); making the caller
   prompt say explicitly that a fact asked again must come back with the same value is the one
   change most likely to move `dialogue_consistency_rate`. Owner: §5.2 of `50-voice-pipeline.md`.
2. **Raise `llm_generator_max_tokens` for models that now hit `SCHEMA_INVALID`**, or teach the
   grammar to close the JSON earlier. Not needed for the 2B (1 occurrence in 46).
3. **Split `dialogue_consistency_rate`** into `answered_differently` and `answered_once`.
4. **Record the rejected raw generation** alongside the failure code. Today `spoken` holds the
   fallback text, so a code cannot be traced to the text that earned it.

## 6. chars per output token (`validator.estimate_tokens`)

Measured on the **explanation** suite only — plain Russian prose, no JSON wrapper, so
`len(completion.text) / usage.completion_tokens` is exactly "chars per completion token on real
Russian completions". (The interpreter and dialogue suites' `chars_per_output_token` mixes JSON
scaffolding into the token count and is *not* the right ratio for this constant.) Pooled over all
three passes of 2026-09-22, which is the largest honest sample available:

| Model | chars | completion tokens | chars/token | vs the constant 3 |
|:--|--:|--:|--:|--:|
| Qwen3-4B | 2593 | 911 | 2.846 | −5.1 % |
| Qwen3.5-0.8B | 3764 | 1199 | 3.139 | +4.6 % |
| **Qwen3.5-2B (the DEV default)** | 2077 | 570 | **3.644** | **+21.5 %** |
| Qwen3.5-4B | 2753 | 658 | 4.184 | +39.5 % |

`_CHARS_PER_TOKEN` is **3** (`backend/app/application/dialogue/validator.py:93`). R6's rule changes
the constant only when the DEV default's measurement is more than 25 % off; at **+21.5 %** it is
not, so **the constant is left at 3** and `estimate_tokens`, its docstring and its tests are
unchanged. Three is also the conservative side: a lower chars/token makes `estimate_tokens`
over-count, which makes the §7.1 length check fire earlier, never later. Worth re-checking if the
default ever moves to a 4B, where the measurement is +39.5 %.

## 7. Gaps and deviations

1. **`ttft_ms` is empty by construction** — see §2. Not a harness gap.
2. **`hardware` is empty on a `NOT_RUN`/`FAILED` envelope** — `_common.not_run()` and the
   equivalent `FAILED` envelope are built before the NVML read. The `reason` is what those results
   are for.
3. **`runs: 1` per model.** Three passes of the same five runs were made on 2026-09-22 (04:58,
   05:07 and 05:27 UTC); only the last, post-fix pass is committed, and §3/§6 quote the earlier
   ones where the comparison is the evidence.
4. **`benchmarks/data/` is gitignored** by `.gitignore:12`'s bare `data/` pattern, so the corpora
   these numbers were produced from cannot currently be committed. E19-F raised the same blocker.
5. **`_common.write_result()`'s same-second overwrite is fixed** (E19-B2: millisecond timestamps
   plus a collision-suffix refusal). Each run here still writes to its own `--out` directory, which
   costs nothing and keeps a run's files together.
