# `ru_sample.wav`

| | |
|:--|:--|
| Source | `https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM/example.wav` — the GigaAM project's own published example recording, linked from `gigaam.utils.download_short_audio()` in `salute-developers/GigaAM` (README "Load test audio" example) |
| Licence | MIT (`salute-developers/GigaAM` repository licence) |
| Format | already 16 kHz mono PCM s16le WAV, 11.29 s, 361,324 bytes — no conversion needed |
| sha256 | `d8aaaa18a5098d7c6de0595ae7ac1e64cacd0d4022af3595213bdaf23be77e69` |

## Expected transcript

The GigaAM project's own `colab_example.ipynb` publishes the transcript this exact recording
produces (via `ai-sage/GigaAM-Multilingual`, `revision="ctc"`, word timestamps) — the first lines
of Pushkin's «У лукоморья дуб зелёный»:

```
ничьих не требуя похвал счастлив уж я надеждой сладкой что дева с трепетом любви
посмотрит может быть украдкой на песни грешные мои у лукоморья дуб зеленый
```

`backend/tests/models/test_gigaam_provider.py` uses this as `_EXPECTED_TEXT` and asserts a word
error rate <= 0.2 against it (after lowercasing, stripping punctuation and ё->е normalisation) for
both `v3_e2e_ctc` and `v3_ctc`. It is the published project's own transcript for this audio, not
this task's own model output checked against itself.
