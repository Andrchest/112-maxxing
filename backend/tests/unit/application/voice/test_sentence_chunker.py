"""`split_for_tts` and `ChunkedTtsStream` (HLD `50-voice-pipeline.md` §2.4, §6.1; SPEC §18).

The splitter is pure, so its whole contract is a table plus one property; the stream needs an
event loop and a `FakeTTS`, and nothing else.
"""

from __future__ import annotations

import itertools

import pytest
from app.application.ports.tts import TtsVoiceSpec
from app.application.voice.sentence_chunker import (
    ChunkedTtsStream,
    TextUnit,
    split_for_tts,
)
from app.inference.tts.fake_tts import FakeTTS

VOICE = TtsVoiceSpec(voice_id="ru_female_1", speaking_rate=1.0)


def texts(units: tuple[TextUnit, ...]) -> list[str]:
    return [unit.text for unit in units]


# ---------------------------------------------------------------------------------------------
# The splitter
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("Алло.", ["Алло."]),
        ("Алло. Я слушаю.", ["Алло. ", "Я слушаю."]),
        ("Горит! Быстрее!", ["Горит! ", "Быстрее!"]),
        ("Что? Не слышу…", ["Что? ", "Не слышу…"]),
        # No trailing whitespace after the ender: one unit, and the ender stays where it was.
        ("Да?!", ["Да?!"]),
        # A trailing space after the last sentence belongs to that sentence.
        ("Да. ", ["Да. "]),
    ],
)
def test_sentences_split_only_on_a_boundary(text: str, expected: list[str]) -> None:
    """Rule 1: an ender splits only when whitespace or the end of the text follows it."""
    assert texts(split_for_tts(text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Улица Ленина, д. 5, квартира 12.",
        "Это кв. 12 на пятом этаже.",
        "Мы на ул. Мира.",
        "Там т.е. около магазина.",
        "Температура 36.6 градуса.",
        "Цена 1.5 тысячи.",
        "Дом 27. окончание",
        "А. Петров звонит.",
    ],
)
def test_an_abbreviation_a_number_or_an_initial_never_splits(text: str) -> None:
    """Rule 2: «д.», «кв.», «ул.», «т.е.», a decimal and an initial are not sentence ends."""
    units = split_for_tts(text)
    assert len(units) == 1, texts(units)


def test_an_abbreviation_inside_a_real_sentence_keeps_the_real_boundary() -> None:
    """The exemption is for the abbreviation's own dot, not for the sentence it sits in."""
    units = split_for_tts("Улица Ленина, д. 5. Приезжайте быстрее.")

    assert texts(units) == ["Улица Ленина, д. 5. ", "Приезжайте быстрее."]


def test_a_long_sentence_is_subdivided_at_clause_separators() -> None:
    """Rule 3: over `max_unit_chars`, the cut goes to a comma — never inside a word."""
    text = (
        "Я звоню потому что у нас в подъезде очень сильно пахнет дымом, "
        "соседи уже вышли на улицу, а лифт совсем не работает."
    )
    units = split_for_tts(text, max_unit_chars=60)

    assert len(units) > 1
    assert all(len(unit.text) <= 80 for unit in units), texts(units)
    for unit in units[:-1]:
        # Every cut lands after a separator plus its whitespace, i.e. never mid-word.
        assert unit.text.rstrip().endswith((",", ";", ":", "—", "–", "-"))


def test_a_long_sentence_with_no_separator_is_left_whole() -> None:
    """A correct long unit beats a unit cut inside a word (rule 3's last line)."""
    text = "а" * 300

    assert texts(split_for_tts(text, max_unit_chars=50)) == [text]


def test_a_decimal_comma_is_never_a_cut_point() -> None:
    """`[,;:]` only cuts when whitespace follows — «0,5» stays one number."""
    text = "Там примерно 0,5 километра до места где всё это происходит прямо сейчас у нас."
    units = split_for_tts(text, max_unit_chars=30)

    assert all("0,5" in unit.text or "0,5" not in text for unit in units)
    assert "".join(texts(units)) == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Алло.",
        "Алло. Я слушаю. Что случилось?",
        "Улица Ленина, д. 5, кв. 12. Приезжайте!",
        "  Пробелы   в  начале. И в конце.  ",
        "Температура 36.6. Давление 120/80.",
        "Один… Два… Три…",
        "а" * 250,
        "Раз, два, три, четыре, пять, шесть, семь, восемь, девять, десять, одиннадцать, "
        "двенадцать, тринадцать, четырнадцать.",
    ],
)
@pytest.mark.parametrize("limit", [10, 40, 120, 500])
def test_units_concatenate_back_to_the_original_text(text: str, limit: int) -> None:
    """Rule 4, the property `delivered_text`'s correctness rests on (§6.3)."""
    units = split_for_tts(text, max_unit_chars=limit)

    assert "".join(unit.text for unit in units) == text
    for unit in units:
        assert text[unit.start : unit.end] == unit.text
    for left, right in itertools.pairwise(units):
        assert left.end == right.start


def test_splitting_is_deterministic() -> None:
    """Same text, same units — a chunker whose output moved would move the alignment with it."""
    text = "Алло. Улица Ленина, д. 5. Приезжайте быстрее!"

    assert split_for_tts(text) == split_for_tts(text)


# ---------------------------------------------------------------------------------------------
# `ChunkedTtsStream`
# ---------------------------------------------------------------------------------------------


async def drain(stream: ChunkedTtsStream) -> list[object]:
    return [chunk async for chunk in stream]


async def test_offsets_are_rebased_onto_the_whole_text() -> None:
    """A unit's chunk offsets index the unit; the stream's index the whole utterance (§2.4)."""
    text = "Алло. Я слушаю."
    stream = ChunkedTtsStream(FakeTTS(), text, VOICE, request_id="r", max_chunk_ms=40)

    chunks = [chunk async for chunk in stream]

    assert chunks, "the fake must produce audio for a non-empty text"
    assert chunks[0].text_offset_start == 0
    assert chunks[-1].text_offset_end == len(text)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert 0 <= chunk.text_offset_start <= chunk.text_offset_end <= len(text)


async def test_every_unit_is_one_provider_request() -> None:
    """Ruling (3): one request per unit is what gives `cancel()` its granularity."""
    provider = FakeTTS()
    text = "Алло. Я слушаю. Что случилось?"
    stream = ChunkedTtsStream(provider, text, VOICE, request_id="r", max_chunk_ms=40)

    await drain(stream)

    assert len(provider.requests) == len(stream.units) == 3
    assert [request[0] for request in provider.requests] == [u.text for u in stream.units]
    assert [request[2] for request in provider.requests] == ["r:0", "r:1", "r:2"]


async def test_cancel_stops_after_the_unit_in_flight_and_issues_no_further_request() -> None:
    """§6.1 step 2 / ruling (3): the in-flight unit's audio is discarded, never played."""
    provider = FakeTTS()
    text = "Алло. Я слушаю. Что случилось?"
    stream = ChunkedTtsStream(provider, text, VOICE, request_id="r", max_chunk_ms=40)

    yielded = []
    async for chunk in stream:
        yielded.append(chunk)
        if len(yielded) == 2:
            await stream.cancel()

    assert stream.cancelled is True
    # One request was issued (the unit in flight); the other two units were never asked for.
    assert len(provider.requests) == 1
    # Nothing was yielded after the cancel.
    assert len(yielded) == 2
    assert yielded[-1].chunk_index == 1


async def test_cancel_before_the_first_chunk_issues_no_request_at_all() -> None:
    """Cancelling a stream that has not started must not reach the provider."""
    provider = FakeTTS()
    stream = ChunkedTtsStream(provider, "Алло. Я слушаю.", VOICE, request_id="r")

    await stream.cancel()
    chunks = await drain(stream)

    assert chunks == []
    assert provider.requests == []


async def test_cancel_is_idempotent() -> None:
    """The port says so (§2.4)."""
    stream = ChunkedTtsStream(FakeTTS(), "Алло.", VOICE, request_id="r")

    await stream.cancel()
    await stream.cancel()

    assert stream.cancelled is True


async def test_the_stream_reports_the_exact_text_it_was_given() -> None:
    """SPEC §25: what is persisted is the text handed to the provider, not a normalisation."""
    text = "  Алло.  "
    stream = ChunkedTtsStream(FakeTTS(), text, VOICE, request_id="r")

    assert stream.text == text
    assert stream.request_id == "r"
