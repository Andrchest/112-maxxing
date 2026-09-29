"""Pure text/audio helpers vendored from the owner's TTS lab (I8 V1, A1-plan §2.1 item 4).

SOURCE: `~/emo-lab/tools/qwen3_pipeline.py` at emo-lab commit
`5a02e3e838da2573bde3c9deb65635532ff69fc6` (the file's own last change: `1721ad8`, "cap segment
generation with max_new_tokens=480"). Copied, not imported: the lab is a read-only reference, and
this worker must not depend on a second repository at run time. What was taken, verbatim apart
from formatting, one lint fix (`round` already returns an int) and these comments:

* `segment_text` — the worker's safety net for a unit that still exceeds `SAFETY_NET_MAX_CHARS`
  after the client's own splitter (`app.application.voice.sentence_chunker.split_for_tts`, which
  owns the ordinary `tts.max_unit_chars` split and its stricter never-inside-an-abbreviation
  rules);
* `stitch` — joins the safety net's segments with a programmatic pause (pauses are metadata, not
  model output);
* `normalize_numbers` — digits to Russian words, so the model never has to guess how «12» reads.
  Needs `num2words` (this package's `pyproject.toml`); `tts_qwen3.server` degrades to the raw text
  with one WARN when it is not installed, never failing a synthesis;
* `restore_yo` — vendored with its tests because the plan names it, but **not applied** by the
  worker: its ж/ш heuristic rewrites common caller words wrongly («уже» -> «ужё», «жена» ->
  «жёна», «решение» -> «решёние»; see `tests/test_pipeline.py`). Wiring it live would need a
  vetted dictionary first.

Not taken: `add_stress` (the lab notes CustomVoice treats U+0301 as noise), the lab's style
prompts (the backend's `app.inference.tts.instruct` owns the evaluated presets, STYLE_VERSION 2)
and `run_pipeline` (this worker's `/synthesize` is the orchestration).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import numpy as np

__all__ = [
    "normalize_numbers",
    "restore_yo",
    "segment_text",
    "stitch",
]

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

# Curated ё-words (lowercase lemma -> canonical form). Extended by the
# ж/ш heuristic below. Deliberately conservative: for TTS a missed ё is a
# mild prosody miss, a wrong ё can corrupt the word.
_YO_WORDS: dict[str, str] = {
    "ее": "её",
    "нею": "неё",
    # ж-words
    "желтый": "жёлтый",
    "желтая": "жёлтая",
    "желтое": "жёлтое",
    "желтые": "жёлтые",
    "желтую": "жёлтую",
    "желтой": "жёлтой",
    "желтом": "жёлтом",
    "желтыми": "жёлтыми",
    "жесткий": "жёсткий",
    "жесткая": "жёсткая",
    "жесткие": "жёсткие",
    "жестко": "жёстко",
    "жесткости": "жёсткости",
    "желудь": "жёлудь",
    "желудок": "жёлудок",
    "желудки": "жёлудки",
    "желудочек": "жёлудочек",
    "желчь": "жёлчь",
    "желток": "жёлток",
    # ш-words
    "шел": "шёл",
    "шелк": "шёлк",
    "шелка": "шёлка",
    "шелком": "шёлком",
    "шелковый": "шёлковый",
    "шепот": "шёпот",
    "шепотом": "шёпотом",
    # ё-words
    "елка": "ёлка",
    "елки": "ёлки",
    "елочка": "ёлочка",
    "елочки": "ёлочки",
    "елочный": "ёлочный",
    "еж": "ёж",
    "ежи": "ёжи",
    "ежик": "ёжик",
    "ежики": "ёжики",
    "ех": "ёх",
    "ехидна": "ёхидна",
    "ехидный": "ёхидный",
    "ехидство": "ёхидство",
    # -ёт/-ёте/-ём verbs
    "живет": "живёт",
    "живете": "живёте",
    "живем": "живём",
    "поет": "поёт",
    "поете": "поёте",
    "поём": "поём",
    "гудет": "гудёт",
    "гудеть": "гудеть",
    "плывет": "плывёт",
    "плывете": "плывёте",
    "плывем": "плывём",
    "ведет": "ведёт",
    "ведете": "ведёте",
    "ведем": "ведём",
    "вел": "вёл",
    # мёд
    "мед": "мёд",
    "меду": "мёду",
    "меда": "мёда",
    "медом": "мёдом",
    "меди": "мёди",
}

# Words where ж/ш + е is NOT ё. The heuristic would otherwise corrupt them.
_YO_BLOCKLIST: frozenset[str] = frozenset(
    {
        "шея",
        "шеи",
        "шей",
        "шее",
        "шеям",
        "шеями",
        "шедевр",
        "шедевров",
        "шедевру",
        "шеф",
        "шефа",
        "шефу",
        "шефам",
        "шефами",
        "шезлонг",
        "шезлонгов",
        "шерсть",
        "шерсти",
        "шерстя",
        "шерстяной",
        "шесть",
        "шестой",
        "шестая",
        "шестое",
        "шестом",
        "шестерка",
        "шестеро",
        "шелуха",
        "жертва",
        "жертвы",
        "жертв",
        "жертве",
        "жертвовать",
        "жердь",
        "жерди",
        "жерло",
        "жерла",
        "жернов",
        "жернова",
        "жерновок",
        "жерех",
        "жереха",
        "жест",
        "жеста",  # "жест" (gesture) has no ё
        "жестяной",
        "жестянка",
        "желание",
        "желания",
        "желать",
        "желаю",
        "желаешь",
        "желает",
        "желающий",
        "желающая",
        "желающее",
        "желанный",
        "желанная",
        "желоб",
        "желоба",
    }
)

_WORD_RE = re.compile(r"[а-яА-ЯёЁ]+")


def _restore_yo_word(word: str) -> str:
    lower = word.lower()
    if lower in _YO_WORDS:
        mapped = _YO_WORDS[lower]
        if word[0].isupper():
            mapped = mapped[0].upper() + mapped[1:]
        return mapped
    if lower in _YO_BLOCKLIST:
        return word
    # Heuristic: ё is used almost always after ж/ш. Replace the first е
    # following ж or ш (not already ё).
    for i, ch in enumerate(lower):
        if ch in "жш" and i + 1 < len(lower) and lower[i + 1] == "е":
            chars = list(word)
            chars[i + 1] = "ё" if word[i + 1].islower() else "Ё"
            return "".join(chars)
    return word


def restore_yo(text: str) -> str:
    """Restore ё using a curated dictionary plus a conservative ж/ш rule (NOT applied live —
    see the module docstring)."""
    return _WORD_RE.sub(lambda m: _restore_yo_word(m.group(0)), text)


_INT_RE = re.compile(r"(?<!\d)\d+(?!\d)")
_DECIMAL_RE = re.compile(r"(?<!\d)\d+[.,]\d+(?!\d)")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _num_to_words(value: float) -> str:
    from num2words import num2words

    words: str = num2words(value, lang="ru")
    return words


def normalize_numbers(text: str) -> str:
    """Spell out standalone numbers and percentages for stable prosody.

    Order matters: percentages, then decimals, then bare integers. Decimals
    are consumed first so a sentence-ending period ("Ленина, 12.") does not
    masquerade as a decimal and block the integer conversion.

    Raises `ImportError` when `num2words` is not installed and `text` has a digit.
    """
    text = _PERCENT_RE.sub(
        lambda m: f"{_num_to_words(float(m.group(1).replace(',', '.')))} процентов",
        text,
    )
    text = _DECIMAL_RE.sub(lambda m: _num_to_words(float(m.group(0).replace(",", "."))), text)
    text = _INT_RE.sub(lambda m: _num_to_words(int(m.group(0))), text)
    return text


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")


def segment_text(text: str, max_chars: int = 140) -> list[str]:
    """Split into phrase-level chunks for stable long-form generation.

    Qwen3-TTS degrades on long single-sequence generation (tempo drift,
    swallowed punctuation), so generate 1-2 logical sentences per segment.
    """
    text = text.strip()
    if not text:
        return []
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    segments: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            segments.append(sentence)
            continue
        # Long sentence: split on commas/semicolons keeping chunks bounded.
        clauses = re.split(r"(?<=[,;:])\s+", sentence)
        buffer = ""
        for clause in clauses:
            candidate = f"{buffer} {clause}".strip()
            if buffer and len(candidate) > max_chars:
                segments.append(buffer)
                buffer = clause
            else:
                buffer = candidate
        if buffer:
            segments.append(buffer)
    # Merge tiny fragments into their neighbour (a lone "Да." after a long
    # sentence is better attached than generated as a 2-frame segment).
    merged: list[str] = []
    for segment in segments:
        if merged and len(segment) < 6:
            merged[-1] = f"{merged[-1]} {segment}"
        else:
            merged.append(segment)
    return merged


# ---------------------------------------------------------------------------
# Deterministic stitching
# ---------------------------------------------------------------------------


def stitch(
    wavs: Sequence[np.ndarray],
    sample_rate: int,
    pauses: Sequence[float] | None = None,
) -> np.ndarray:
    """Concatenate segment waveforms with exact programmatic pauses.

    pauses[i] is the silence (seconds) between segment i and i+1. If None,
    no extra silence is inserted (the model's own boundaries remain).
    """
    if not wavs:
        raise ValueError("no segments to stitch")
    if pauses is not None and len(pauses) >= len(wavs):
        raise ValueError("pauses must have at most len(wavs)-1 entries")
    parts: list[np.ndarray] = []
    for index, wav in enumerate(wavs):
        parts.append(np.asarray(wav, dtype=np.float32).reshape(-1))
        if pauses is not None and index < len(pauses) and pauses[index] > 0:
            parts.append(np.zeros(round(sample_rate * float(pauses[index])), dtype=np.float32))
    return np.concatenate(parts)
