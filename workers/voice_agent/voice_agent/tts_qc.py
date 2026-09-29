"""Offline quality check for one pre-synthesised clip (I8 A1 §2.2 "offline" tier, I8 V4).

Two pure checks, both computed from the clip alone:

* **CER** — the clip is transcribed back through an injected `AsrPort` and compared, character by
  character, against the text that was meant to be spoken. `normalize_for_cer` folds away the
  differences a correct-but-superficially-different transcript would otherwise fail on: case,
  punctuation, `ё`/`е`, and digit runs spelled out as Russian words (a Qwen3-TTS clip never says a
  digit — the worker's own `normalize_numbers`, I8 V1, spells it out before synthesis — so the
  reference must be spelled out the same way before the two are compared).
* **Rate** — `chars_per_s = (letters + digits in the text) / audio_s`; a clip far outside the
  normal speaking-rate band is a runaway or a truncated generation regardless of what GigaAM made
  of it (mirrors the live worker's own rate guard, I8 V1 `tts_qwen3/server.py`).

`check_clip` runs the rate check unconditionally and the CER check only against a *real* ASR:
`asr is None` (never loaded, or its warm-up failed) or `asr.provider_name == "fake"` (the gate's
scripted `FakeASR`, which would make every clip pass or fail by test fiat, never by anything the
clip's own audio said) both degrade to the rate check alone — `QcOutcome.checked_cer` says which
happened, and `tts_cache.py`'s sidecar JSON carries that flag through to disk.

Nothing here constructs an ASR provider, opens a file or knows about `TtsLineCache`: the port is
injected, the caller decides what to do with the verdict.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "CER_THRESHOLD",
    "FAKE_ASR_PROVIDER_NAME",
    "MAX_CHARS_PER_S",
    "MIN_CHARS_PER_S",
    "AsrPort",
    "QcOutcome",
    "character_error_rate",
    "chars_per_second",
    "check_clip",
    "normalize_for_cer",
    "rate_ok",
    "spoken_chars",
]

#: I8 A1 §2.2 / the brief: a clip whose GigaAM transcript disagrees with the text by more than
#: this fraction of characters is not trusted for the cache.
CER_THRESHOLD = 0.15
#: I8 A1 §2.2's live rate guard, reused offline: below this, the clip is a runaway (dead air,
#: stutter); above it, the clip is almost certainly truncated.
MIN_CHARS_PER_S = 6.0
MAX_CHARS_PER_S = 22.0
#: `ASRProvider.provider_name` for the gate's scripted double (`app.inference.asr.fake_asr`).
FAKE_ASR_PROVIDER_NAME = "fake"

_YO = str.maketrans({"ё": "е", "Ё": "Е"})
_DIGIT_RUN = re.compile(r"\d+")
_NOT_WORD = re.compile(r"[^0-9a-zа-я ]+")

#: A compact Russian cardinal speller, nominative/masculine forms only (I8 V4: good enough for a
#: CER *comparison*, not a TTS text-normaliser — no case/gender agreement, no fraction/ordinal
#: forms). None of today's eight fallback templates contain a digit; this exists so a template
#: that later does still gets a fair CER instead of a guaranteed near-miss against a real ASR's
#: transcript. Mirrors what the worker's own `pipeline.normalize_numbers` (vendored from
#: `~/emo-lab`, I8 V1) is expected to have already spoken.
_ONES = (
    "ноль",
    "один",
    "два",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_TENS = (
    "",
    "",
    "двадцать",
    "тридцать",
    "сорок",
    "пятьдесят",
    "шестьдесят",
    "семьдесят",
    "восемьдесят",
    "девяносто",
)
_HUNDREDS = (
    "",
    "сто",
    "двести",
    "триста",
    "четыреста",
    "пятьсот",
    "шестьсот",
    "семьсот",
    "восемьсот",
    "девятьсот",
)


def _plural_form_ru(n: int, forms: tuple[str, str, str]) -> str:
    """`forms = (one, few, many)`, e.g. `("тысяча", "тысячи", "тысяч")` — standard Russian
    numeral agreement (11-14 always "many", else by the last digit)."""
    last_two = n % 100
    if 11 <= last_two <= 14:
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def _below_thousand(n: int, *, feminine: bool = False) -> list[str]:
    words: list[str] = []
    if n >= 100:
        words.append(_HUNDREDS[n // 100])
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
    if n > 0 or not words:
        # "две тысячи", never "два тысячи" — тысяча is feminine; every other group word here
        # (сто..девяносто, миллион) is masculine/neutral, so only this one word needs the swap.
        words.append("две" if feminine and n == 2 else _ONES[n])
    return words


def _number_to_words_ru(n: int) -> str:
    """`27` -> `"двадцать семь"`, `2026` -> `"две тысячи двадцать шесть"`. `0 <= n`; a value this
    speller has no group word for (>= 10**9) is returned as digits, unchanged."""
    if n == 0:
        return _ONES[0]
    if n >= 1_000_000_000:
        return str(n)
    words: list[str] = []
    millions, n = divmod(n, 1_000_000)
    if millions:
        words += _below_thousand(millions)
        words.append(_plural_form_ru(millions, ("миллион", "миллиона", "миллионов")))
    thousands, n = divmod(n, 1000)
    if thousands:
        words += _below_thousand(thousands, feminine=True)
        words.append(_plural_form_ru(thousands, ("тысяча", "тысячи", "тысяч")))
    if n or not words:
        words += _below_thousand(n)
    return " ".join(words)


def _spell_digit_runs(text: str) -> str:
    return _DIGIT_RUN.sub(lambda match: _number_to_words_ru(int(match.group())), text)


def normalize_for_cer(text: str) -> str:
    """Lower-case, no punctuation, `ё`->`е`, numbers as words — the brief's own four steps, in
    that order (digits are spelled out before the punctuation strip, so the words they produce
    survive it)."""
    folded = unicodedata.normalize("NFKC", text).translate(_YO)
    spelled = _spell_digit_runs(folded).lower()
    stripped = _NOT_WORD.sub(" ", spelled)
    return " ".join(stripped.split())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance over `normalize_for_cer`-folded strings, divided by the reference's
    length. An empty (post-fold) reference scores 0.0 for an empty hypothesis, else 1.0."""
    ref = normalize_for_cer(reference)
    hyp = normalize_for_cer(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def spoken_chars(text: str) -> int:
    """Letters and digits only — the same counting rule the live worker's token cap uses (I8 V1,
    `tts_qwen3/server.py`), so the cache's rate check and the worker's agree on what "chars"
    means."""
    return sum(1 for ch in text if ch.isalnum())


def chars_per_second(text: str, audio_ms: int) -> float:
    """0.0 for a zero- or negative-length clip (that clip fails `rate_ok` on its own merits)."""
    if audio_ms <= 0:
        return 0.0
    return spoken_chars(text) * 1000.0 / audio_ms


def rate_ok(text: str, audio_ms: int) -> bool:
    rate = chars_per_second(text, audio_ms)
    return MIN_CHARS_PER_S <= rate <= MAX_CHARS_PER_S


@runtime_checkable
class AsrPort(Protocol):
    """The slice of `app.application.ports.asr.ASRProvider` this module needs. A real
    `GigaAMProvider` and the gate's `FakeASR` both satisfy it already; nothing here imports
    either."""

    @property
    def provider_name(self) -> str: ...

    async def transcribe(self, audio: bytes, sample_rate: int, *, request_id: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class QcOutcome:
    """One clip's QC verdict — what `tts_cache.py` writes to the sidecar JSON."""

    passed: bool
    chars_per_s: float
    cer: float | None
    checked_cer: bool
    asr_provider: str | None
    reason: str | None = None
    """`None` when `passed`; else `"rate"` or `"cer"` — whichever check failed first."""


async def check_clip(
    *,
    text: str,
    pcm: bytes,
    sample_rate: int,
    audio_ms: int,
    asr: AsrPort | None,
    request_id: str,
    cer_threshold: float = CER_THRESHOLD,
) -> QcOutcome:
    """The rate check, plus a CER check when `asr` is a real, loaded provider (see the module
    docstring). `pcm` is never inspected beyond what `asr.transcribe` does with it."""
    rate = chars_per_second(text, audio_ms)
    rate_passed = MIN_CHARS_PER_S <= rate <= MAX_CHARS_PER_S
    provider_name = asr.provider_name if asr is not None else None
    if asr is None or provider_name == FAKE_ASR_PROVIDER_NAME:
        return QcOutcome(
            passed=rate_passed,
            chars_per_s=rate,
            cer=None,
            checked_cer=False,
            asr_provider=provider_name,
            reason=None if rate_passed else "rate",
        )
    result = await asr.transcribe(pcm, sample_rate, request_id=request_id)
    hypothesis = getattr(result, "text", "") or ""
    error = character_error_rate(text, hypothesis)
    cer_passed = error <= cer_threshold
    passed = rate_passed and cer_passed
    reason = None if passed else ("rate" if not rate_passed else "cer")
    return QcOutcome(
        passed=passed,
        chars_per_s=rate,
        cer=error,
        checked_cer=True,
        asr_provider=provider_name,
        reason=reason,
    )
