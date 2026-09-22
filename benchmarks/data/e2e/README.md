# E2E turn corpus (`benchmarks/benchmark_e2e.py`, SPEC §40, HLD 60 §7.4)

Nine **trainee-side** turns of the demo scenario `scenarios/examples/apartment-fire/v1`, in the
order a System-112 interview takes them. `benchmark_e2e.py` plays each WAV into the pipeline (as
the trainee's microphone) and reads SPEC §27's critical product metric —
`speech_end_to_first_audio_ms` — out of the session event log:
`USER_SPEECH_ENDED` → `CALLER_TTS_STARTED.first_audio_offset_ms`.

## Files

| Path | What it is |
|:--|:--|
| `turns.jsonl` | the manifest; one row per turn |
| `wav/<id>.wav` | 16 kHz mono 16-bit PCM, the trainee's line |
| `build_turns.py` | the committed, deterministic builder (`uv run python benchmarks/data/e2e/build_turns.py`) |

## Manifest row

```json
{"id": "floor", "text": "На каком этаже квартира?", "path": "wav/floor.wav",
 "duration_ms": 1792, "source": "piper:ru_RU-irina-medium", "interrupt_after_ms": 400}
```

* `path` is relative to this directory.
* `source` says plainly who produced the audio (the ASR corpus's R5 honesty rule, applied here
  too): `piper:<voice>` for a synthesized line, `human:<who>` for a recorded one.
* `interrupt_after_ms` is optional and puts the row in the **barge-in sub-suite**: the trainee
  starts speaking that many milliseconds after the caller's first audio, and the benchmark reports
  `cutoff_latency_ms` p50/p95 and `over_250ms_count` against `50-voice-pipeline.md` §6.2's 250 ms
  budget. Two rows carry it today (`floor` 400 ms, `reassurance` 700 ms).

## The turns

| `id` | Line | ms | Barge-in |
|:--|:--|--:|:--|
| `greeting` | Служба сто двенадцать что у вас случилось? | 3168 | |
| `address` | Назовите улицу и номер дома | 3136 | |
| `what_is_burning` | Что именно горит в квартире? | 1824 | |
| `victims` | В квартире остались люди? | 1632 | |
| `floor` | На каком этаже квартира? | 1792 | 400 ms |
| `apartment` | Назовите номер квартиры | 1920 | |
| `phone_confirm` | Подтвердите ваш номер телефона | 2016 | |
| `reassurance` | Пожарные уже выехали оставайтесь на связи | 2656 | 700 ms |
| `closing` | Информация принята в квартиру не заходите | 3232 | |

Each line is **one breath group with no internal punctuation**, and that is a measured constraint,
not a style choice: Piper puts a real pause at a comma or a sentence break, and a pause longer than
the profile's `endpoint_silence_ms` (320 ms on `DEV_3060TI*`) makes the VAD end the turn there and
begin another. The benchmark handles that correctly — only the first detected turn of a WAV is the
scripted one, the rest are reported as `suite: "followup"` and never aggregated — but one turn per
row keeps the result readable. The earlier, comma-rich version of this corpus produced 7 followups
from 9 rows; this one produces 3 (two of which are the scripted barge-in bursts themselves).

The questions are the ones the demo scenario has facts for (street, house, floor — where the caller
believes the 5th and the world says the 4th — apartment, phone), so the dialogue chain is asked for
the addresses and numbers the §28 assessment rules actually score, not for generic Russian.

## Honesty: this is Piper speaking, not a person

Every WAV is synthesized on CPU by `ru_RU-irina-medium`, the same Piper voice the CPU TTS fallback
uses. **A latency measured on this corpus is the pipeline's latency on Piper's pronunciation of
dispatcher Russian, not on human speech**: real trainees have hesitations, breaths, background
noise and regional pronunciation, all of which change how long the VAD waits for an endpoint and
how hard GigaAM has to work. The end-to-end number is dominated by model time rather than by who
spoke, so the figure is meaningful — but it is not a field measurement and `docs/benchmarks/e2e.md`
says so beside every table.

Piper runs at 22 050 Hz; `build_turns.py` converts to the pipeline's 16 kHz mono through the
product's own `app.application.voice.resampler.Resampler`, so the samples the VAD and GigaAM see
here went through the same downmix → linear-interpolation → peak-normalise chain a real LiveKit
call's audio does (§3.1).

The build is **not byte-for-byte reproducible**: Piper's VITS graph draws its noise inside the ONNX
graph, so no Python-side seed pins it (the same measured fact
`benchmarks/data/warmup/build_warmup.py` documents). The committed WAVs are a one-time build
output; what is checked is the format, the ≤ 3 MB total budget (720 KB today) and that every row
resolves.

## Adding a human recording

1. Record one trainee line, save it as 16 kHz mono 16-bit PCM WAV under `wav/`.
2. Append a manifest row with `source: "human:<who>"` and the real `duration_ms`.

Nothing in `benchmark_e2e.py` needs changing — it reads `path` and plays whatever is there. Keep
the committed total under 3 MB; anything larger belongs outside the repository with a pointer here.
