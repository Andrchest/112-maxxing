"""`tts_qwen3.pipeline` — the helpers vendored from the owner's TTS lab (I8 V1).

Adapted from `~/emo-lab/tests/test_qwen3_pipeline.py` at emo-lab commit
`5a02e3e838da2573bde3c9deb65635532ff69fc6`: the cases for the four vendored functions, unchanged in
substance; the style-prompt, `generation_kwargs`, `run_pipeline` and `add_stress` cases are not
here because those functions were not vendored (see `pipeline.py`'s docstring). Added: the words
that keep `restore_yo` out of the live path, and the safety-net sizes this worker uses.
No GPU, no torch; the `normalize_numbers` cases skip when `num2words` is not installed.
"""

from __future__ import annotations

import numpy as np
import pytest
from tts_qwen3 import pipeline as p
from tts_qwen3.server import SAFETY_NET_MAX_CHARS


def test_restore_yo_dictionary() -> None:
    assert p.restore_yo("ее звали мари") == "её звали мари"
    assert p.restore_yo("он шел в желтый дом") == "он шёл в жёлтый дом"
    assert p.restore_yo("Жесткий кейс") == "Жёсткий кейс"
    assert p.restore_yo("вкусный мед") == "вкусный мёд"


def test_restore_yo_blocklist_not_corrupted() -> None:
    for word in ("шея", "шедевр", "шеф", "шерсть", "шесть", "жертва", "желание", "жерло"):
        assert p.restore_yo(word) == word, word


def test_restore_yo_corrupts_common_caller_words_which_is_why_it_is_not_applied_live() -> None:
    """The ж/ш heuristic's known misses: if this ever stops failing, it may be wired in."""
    assert p.restore_yo("уже") == "ужё"
    assert p.restore_yo("жена") == "жёна"
    assert p.restore_yo("решение") == "решёние"


def test_normalize_numbers() -> None:
    pytest.importorskip("num2words")
    out = p.normalize_numbers("вызвана 2 машина, рост 7,5%")
    assert "два" in out and "машина" in out
    assert "семь" in out and "процентов" in out
    assert "2" not in out and "7,5" not in out


def test_normalize_numbers_sentence_period_and_decimals() -> None:
    pytest.importorskip("num2words")
    # Sentence-ending period after a number must not block conversion.
    out = p.normalize_numbers("Я на Ленина, 12. Помогите.")
    assert "двенадцать" in out
    assert "12" not in out
    # Decimals are spelled out, not split apart.
    out2 = p.normalize_numbers("температура 36,6 и рост 7.5%")
    assert "36,6" not in out2 and "7.5" not in out2
    assert "процентов" in out2


def test_normalize_numbers_leaves_digit_free_text_alone_even_without_num2words() -> None:
    """No digit, no `num2words` import: the worker's common case never needs the package."""
    assert p.normalize_numbers("Помогите, горит!") == "Помогите, горит!"


def test_segment_text_basic() -> None:
    segments = p.segment_text("Первая фраза. Вторая, побольше. Да.")
    assert segments[0] == "Первая фраза."
    assert segments[1].startswith("Вторая")
    # tiny trailing fragment merged
    assert segments[-1].endswith("Да.")
    assert len(segments) == 2


def test_segment_text_long_sentence_split() -> None:
    long_sentence = "Это очень длинное предложение, " * 8 + "и оно должно разбиться."
    segments = p.segment_text(long_sentence, max_chars=140)
    assert len(segments) > 1
    assert all(len(s) <= 160 for s in segments)
    assert "".join(segments).count("Это очень длинное предложение,") == 8


def test_segment_text_at_the_workers_safety_net_size() -> None:
    long_sentence = "Это очень длинное предложение, " * 8 + "и оно должно разбиться."
    segments = p.segment_text(long_sentence, max_chars=SAFETY_NET_MAX_CHARS)
    assert len(segments) > 1
    assert all(len(s) <= SAFETY_NET_MAX_CHARS for s in segments)


def test_segment_text_empty() -> None:
    assert p.segment_text("   ") == []


def test_stitch_exact_pauses() -> None:
    sr = 1000
    a = np.ones(100, dtype=np.float32)  # 0.1 s
    b = np.ones(200, dtype=np.float32)  # 0.2 s
    out = p.stitch([a, b], sr, pauses=[0.3])
    assert out.size == 100 + 300 + 200
    assert out[99] == 1.0 and out[100] == 0.0 and out[399] == 0.0 and out[400] == 1.0
    with pytest.raises(ValueError):
        p.stitch([], sr)
    with pytest.raises(ValueError):
        p.stitch([a, b], sr, pauses=[0.1, 0.2])
