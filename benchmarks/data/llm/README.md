# LLM benchmark corpora (`benchmark_llm.py`, SPEC §22/§35/§40/§43, HLD 60 §7.2, E19 ruling R6)

Three committed, deterministic inputs. Nothing here is a measurement; the measurements live in
`docs/benchmarks/results/` and are summarised in `docs/benchmarks/llm.md`.

## `interpreter_cases.jsonl` — 37 rows, 5 marked `uncertain`

Generated from `benchmarks/interpreter_eval/ru_operator_utterances.yaml` (the hand-labelled eval set
E13-B3 built and measured) by `convert_interpreter_cases.py`:

```bash
uv run python benchmarks/data/llm/convert_interpreter_cases.py
```

The YAML stays the single source of truth for the labels — the converter copies `id`, `utterance`,
`expected`, `uncertain` and `notes` verbatim and re-labels nothing. The `scenario` key is carried on
the **first row only**, which is where `benchmark_llm.py` reads it from. Every metric over this
suite is reported **twice**, `overall` and `excluding_uncertain` (E13-B3's ruling).

## `dialogue_cases.jsonl` — 13 multi-turn scripts, 3-4 operator turns each

New in E19. Each row is `{id, category, turns:[{utterance, fact_ids, explicit?}]}` over the demo
scenario `scenarios/examples/apartment-fire/v1`; `category` uses the SPEC §43 category names.

Every script asks **at least one fact twice**, which is what `dialogue_consistency_rate` measures:
the value the caller actually delivered for that fact is folded through
`50-voice-pipeline.md` §7.2's numeral normalisation and the two turns' canonical token sequences are
compared **exactly**. No model judges anything (SPEC §44), and «27» therefore matches
«двадцать семь».

A repeat pair in which the caller never said the value at all (the UNKNOWN /
INCORRECT_BELIEF facts — `incident.cause`, `incident.fire_source`, `hazards.gas_cylinder`) is **not**
counted as consistent; it is counted in `repeat_pairs_never_delivered` instead, so a model that
never answers cannot score 1.0.

The turn's `AllowedFactsPackage` comes from the **real** Fact Access Gate and the forbidden-value
scan is the SPEC §43 matrix reused from `backend/tests/adversarial/test_forbidden_fact_leak_suite.py`
(`Probe`, `gate_for`, `leaked_values`, `honest_answer`, `DEFINITIONS`, `PROFILE`, `EMOTION`,
`STRICT`) — nothing is duplicated here.

Facts whose caller value is spoken (and so are usable as a repeated fact): `address.street`,
`address.house`, `address.apartment`, `address.entrance`, `address.locality`, `address.floor`,
`incident.floor_count`, `incident.type`, `incident.smoke_visible`, `caller.full_name`,
`caller.phone`, `people.victim_01.age`, `people.total_inside`.

## `explanation_fixture.json`

One demo-shaped **good** run (four rules passed, one non-critical rule missed, no critical error) plus
its Russian rule titles — the input to `--suite explanation`, which is the real-model latency number
`docs/hld/60-inference-ops.md` §12 asked for. `report` is validated by
`app.domain.scoring.results.ScoreReport` (pydantic, `extra="forbid"`), so a fixture that drifts out
of the domain shape fails the benchmark instead of silently changing the prompt.

## Running

```bash
# gate-side shape run, fake providers, no GPU
make bench-llm BENCH_ARGS="--provider fake --out /tmp/out"

# real run, one model, under the GPU lock
make bench-llm BENCH_ARGS="--suite all --runs 1 --parallel 2 \
    --model-path models/llm/Qwen3.5-2B-Q4_K_M.gguf"
```
