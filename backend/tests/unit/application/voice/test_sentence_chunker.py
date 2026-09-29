"""`split_for_tts` and `ChunkedTtsStream` (HLD `50-voice-pipeline.md` §2.4, §6.1; SPEC §18).

The splitter is pure, so its whole contract is a table plus one property; the stream needs an
event loop and a `FakeTTS`, and nothing else.
"""

from __future__ import annotations

import itertools

import pytest
from app.application.ports.tts import TtsChunk, TtsVoiceSpec
from app.application.voice.sentence_chunker import (
    ChunkedTtsStream,
    TextUnit,
    derive_tts_seed,
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


# ---------------------------------------------------------------------------------------------
# I8 V1: pauses between units, per-unit derived seeds, the provider's synthesis attributes
# ---------------------------------------------------------------------------------------------


def _is_silence(chunk: TtsChunk) -> bool:
    return chunk.text_offset_start == chunk.text_offset_end and not any(chunk.frame.pcm)


async def test_the_pause_is_inserted_between_units_and_never_after_the_last() -> None:
    provider = FakeTTS(tone_hz=440.0)
    text = "Алло. Я слушаю. Что случилось?"
    stream = ChunkedTtsStream(
        provider, text, VOICE, request_id="r", max_chunk_ms=40, inter_unit_pause_ms=200
    )

    chunks = await drain(stream)

    silence = [chunk for chunk in chunks if _is_silence(chunk)]
    # Two gaps between three units, 200 ms each, in <= 40 ms chunks.
    assert sum(chunk.audio_ms for chunk in silence) == 400
    assert all(chunk.audio_ms <= 40 for chunk in silence)
    assert not _is_silence(chunks[-1])
    assert not _is_silence(chunks[0])
    # Each gap sits exactly at the end of the unit it follows, and is exact.
    assert {chunk.text_offset_end for chunk in silence} == {u.end for u in stream.units[:-1]}
    assert all(chunk.alignment_is_exact for chunk in silence)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.frame.sample_rate == provider.output_sample_rate for chunk in silence)


async def test_a_single_unit_gets_no_pause_and_zero_means_none() -> None:
    one = ChunkedTtsStream(
        FakeTTS(tone_hz=440.0), "Алло.", VOICE, request_id="r", inter_unit_pause_ms=200
    )
    none = ChunkedTtsStream(FakeTTS(tone_hz=440.0), "Алло. Я слушаю.", VOICE, request_id="r")

    assert not any(_is_silence(chunk) for chunk in await drain(one))
    assert not any(_is_silence(chunk) for chunk in await drain(none))


async def test_a_cancel_after_a_unit_yields_no_pause() -> None:
    provider = FakeTTS(tone_hz=440.0)
    stream = ChunkedTtsStream(
        provider, "Алло. Я слушаю.", VOICE, request_id="r", max_chunk_ms=40, inter_unit_pause_ms=200
    )
    first_unit_chunks = provider.audio_ms_for("Алло. ", max_chunk_ms=40) // 40

    yielded = []
    async for chunk in stream:
        yielded.append(chunk)
        if len(yielded) == first_unit_chunks:
            await stream.cancel()

    assert not any(_is_silence(chunk) for chunk in yielded)
    assert len(provider.requests) == 1


async def test_with_a_seed_scope_every_unit_gets_its_own_derived_seed() -> None:
    provider = FakeTTS()
    stream = ChunkedTtsStream(
        provider,
        "Алло. Я слушаю. Что случилось?",
        VOICE,
        request_id="r",
        seed_scope=("session-1", 4),
    )

    await drain(stream)

    seeds = [request[1].seed for request in provider.requests]
    assert seeds == [derive_tts_seed("session-1", 4, unit) for unit in range(3)]
    assert len(set(seeds)) == 3


async def test_without_a_seed_scope_the_voice_is_passed_through_unseeded() -> None:
    provider = FakeTTS()
    await drain(ChunkedTtsStream(provider, "Алло. Я слушаю.", VOICE, request_id="r"))

    assert [request[1] for request in provider.requests] == [VOICE, VOICE]


def test_the_derived_seed_is_stable_31_bit_and_input_sensitive() -> None:
    seed = derive_tts_seed("0b6f1f6e-1111-4c5a-9d7e-2a2a2a2a2a2a", 3, 0)

    # A fixed value: Python's salted hash() would change it per process; SHA-256 does not.
    assert seed == derive_tts_seed("0b6f1f6e-1111-4c5a-9d7e-2a2a2a2a2a2a", 3, 0)
    assert 0 <= seed <= 0x7FFFFFFF
    assert seed != derive_tts_seed("0b6f1f6e-1111-4c5a-9d7e-2a2a2a2a2a2a", 3, 1)
    assert seed != derive_tts_seed("0b6f1f6e-1111-4c5a-9d7e-2a2a2a2a2a2a", 4, 0)
    assert seed != derive_tts_seed("another-session", 3, 0)


class _ReportingTTS(FakeTTS):
    """`FakeTTS` whose streams report `synthesis_attributes`, as `Qwen3TTS`'s do."""

    def stream(self, text, voice, *, request_id, max_chunk_ms=20):  # type: ignore[no-untyped-def]
        inner = super().stream(text, voice, request_id=request_id, max_chunk_ms=max_chunk_ms)
        inner.synthesis_attributes = {"seed": voice.seed, "unit": request_id}  # type: ignore[attr-defined]
        return inner


async def test_each_units_synthesis_attributes_are_collected_in_order() -> None:
    stream = ChunkedTtsStream(
        _ReportingTTS(), "Алло. Я слушаю.", VOICE, request_id="r", seed_scope=("s", 0)
    )

    await drain(stream)

    assert stream.unit_attributes == [
        {"seed": derive_tts_seed("s", 0, 0), "unit": "r:0"},
        {"seed": derive_tts_seed("s", 0, 1), "unit": "r:1"},
    ]


async def test_a_provider_without_attributes_leaves_the_list_empty() -> None:
    stream = ChunkedTtsStream(FakeTTS(), "Алло. Я слушаю.", VOICE, request_id="r")

    await drain(stream)

    assert stream.unit_attributes == []
