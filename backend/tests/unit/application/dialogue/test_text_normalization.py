"""§7.2's normalisation and numeral folding (HLD `50-voice-pipeline.md` §7.2).

The point of these cases is step 5: `27` and «двадцать семь» must produce the *same* canonical
value, or a model can evade §7.5's number check by spelling a digit out. Everything else here is
the machinery that makes that true — `ё`/`е`, case, dashes, quotes, and hyphens/slashes surviving
inside a token.
"""

from __future__ import annotations

import pytest
from app.application.dialogue.text_normalization import normalize_text, token_texts


def test_yo_is_folded_to_ye_and_case_is_dropped() -> None:
    """§7.2 step 1: NFKC, `ё` → `е`, lower case for lexicon matching."""
    assert token_texts("Ёлка ЁЛКА ёлка") == ("елка", "елка", "елка")


def test_the_original_casing_survives_on_the_token() -> None:
    """§7.5's capitalised-name rule reads the original casing, so it must not be lost."""
    tokens = normalize_text("Улица Николаева").tokens
    assert [token.original for token in tokens] == ["Улица", "Николаева"]
    assert [token.text for token in tokens] == ["улица", "николаева"]


@pytest.mark.parametrize("dash", ["‐", "–", "—", "−"])
def test_every_dash_variant_becomes_a_plain_hyphen(dash: str) -> None:
    """§7.2 step 2."""
    assert normalize_text(f"дом{dash}27").normalized == "дом-27"


@pytest.mark.parametrize("quote", ["“", "«", "‘"])
def test_every_quote_variant_becomes_a_plain_quote(quote: str) -> None:
    """§7.2 step 2."""
    assert normalize_text(f"{quote}да").normalized == '"да'


def test_hyphens_and_slashes_stay_inside_a_token() -> None:
    """§7.2 step 3: `27/2` and `дом-27` are one token each, not three."""
    assert token_texts("дом-27 квартира 27/2") == ("дом-27", "квартира", "27/2")


def test_punctuation_separates_tokens() -> None:
    assert token_texts("Да, я слушаю. Что?") == ("да", "я", "слушаю", "что")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("27", "27"),
        ("двадцать семь", "27"),
        ("двадцати семи", "27"),
        ("сто двадцать пять", "125"),
        ("две тысячи", "2000"),
        ("две тысячи пятьсот", "2500"),
        ("девяносто", "90"),
        ("сорока", "40"),
        ("второй", "2"),
        ("двадцатая", "20"),
        ("ноль", "0"),
        ("1985", "1985"),
    ],
)
def test_numeral_folding_is_canonical(text: str, expected: str) -> None:
    """§7.2 step 4/5: digits and spelled-out numerals fold to the same canonical value."""
    assert expected in normalize_text(text).number_values


def test_a_folded_run_records_its_source_span() -> None:
    """§7.2 step 4: "a folded run is recorded with both its canonical value and its source span"."""
    runs = normalize_text("дом двадцать семь").numbers
    assert len(runs) == 1
    assert (runs[0].value, runs[0].first_index, runs[0].last_index) == ("27", 1, 2)


def test_digits_and_words_are_interchangeable_for_the_same_house_number() -> None:
    """The «27» / «двадцать семь» / «д. 27» trio §7.5 depends on."""
    assert normalize_text("27").number_values == normalize_text("двадцать семь").number_values
    assert "27" in normalize_text("д. 27").number_values


def test_a_fraction_word_is_its_own_canonical_value() -> None:
    """§7.2 step 4 lists `половина`, `треть`, `четверть` and they must not fold into a run."""
    assert normalize_text("половина").number_values == frozenset({"1/2"})
    assert normalize_text("двадцать семь с половиной").number_values == {"27", "1/2"}


def test_sentence_starts_are_marked() -> None:
    """§7.5's "not the first token of a sentence" needs sentence boundaries."""
    tokens = normalize_text("Да. Иван тут.").tokens
    assert [token.sentence_start for token in tokens] == [True, True, False]


def test_an_empty_string_normalises_to_nothing() -> None:
    result = normalize_text("")
    assert result.tokens == ()
    assert result.numbers == ()
