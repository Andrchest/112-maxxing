"""`FileTextChecker` over the real packaged data (I4 E35, HLD 71 §71.12, D35).

Runs against `reference/lexicon/` and `reference/streets/` as committed — the same data
`Container` wires by default — so this is also the one place that proves the E23 recon's own
findings survive packaging: the dictionary rejects a real Moscow street («Дубининская»), the
street directory has both of the customer's confused names, and the organizer-verbatim ticket
spelling is flagged, never silently matched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.application.ports.text_checker import StreetStatusKind
from app.infrastructure.reference.spelling_dictionary import SpellingDictionary
from app.infrastructure.reference.street_directory import StreetDirectory
from app.infrastructure.reference.text_checker import (
    DEFAULT_LEXICON_DIR,
    DEFAULT_STREETS_DIR,
    FileTextChecker,
)


def test_default_directories_point_at_the_repo_s_reference_pack() -> None:
    assert DEFAULT_LEXICON_DIR.name == "lexicon"
    assert DEFAULT_LEXICON_DIR.parent.name == "reference"
    assert DEFAULT_STREETS_DIR.name == "streets"


def test_the_checker_loads_from_the_packaged_data() -> None:
    checker = FileTextChecker.load()
    assert checker is not None


def test_a_seeded_misspelling_is_found() -> None:
    """§71.12's acceptance item: a seeded misspelling in checked text is found."""
    checker = FileTextChecker.load()
    assert checker is not None
    spans = checker.misspellings("пажар в подьезде")
    words = {span.word for span in spans}
    assert words == {"пажар", "подьезде"}
    [pazhar] = [span for span in spans if span.word == "пажар"]
    assert "пожар" in pazhar.suggestions


def test_correctly_spelled_text_has_no_misspellings() -> None:
    checker = FileTextChecker.load()
    assert checker is not None
    assert checker.misspellings("пожар в подъезде на первом этаже") == ()


def test_the_dictionary_rejects_a_real_moscow_street_e23_s_own_finding() -> None:
    """E23's finding: the ru_RU dictionary flags «Дубининская» though it is a real street —
    the two checks are independent, on purpose (module docs)."""
    checker = FileTextChecker.load()
    assert checker is not None
    [span] = checker.misspellings("Дубининская улица")
    assert span.word == "Дубининская"
    assert checker.street_status("Дубининская улица").status is StreetStatusKind.KNOWN


def test_both_confused_streets_are_known() -> None:
    checker = FileTextChecker.load()
    assert checker is not None
    assert checker.street_status("Дубнинская улица").status is StreetStatusKind.KNOWN
    assert checker.street_status("Дубининская улица").status is StreetStatusKind.KNOWN


def test_a_kladr_only_moscow_street_is_known() -> None:
    """I5 E41 CHANGE A: a street packaged only in the КЛАДР extract (not in the OSM list) is still
    `KNOWN` — the two directories are unioned. «Елизаровой» does not occur anywhere in the OSM
    file at all, so this is not a normalisation coincidence."""
    checker = FileTextChecker.load()
    assert checker is not None
    assert "Елизаровой" not in (DEFAULT_STREETS_DIR / "osm_moscow_street_names.txt").read_text(
        encoding="utf-8"
    )
    assert checker.street_status("улица Елизаровой").status is StreetStatusKind.KNOWN


def test_an_osm_only_moscow_street_is_still_known() -> None:
    """I5 E41 CHANGE A: adding КЛАДР must not regress a street the OSM list alone already knew.
    «Хапиловский» does not occur anywhere in the КЛАДР file at all."""
    checker = FileTextChecker.load()
    assert checker is not None
    assert "Хапиловский" not in (DEFAULT_STREETS_DIR / "kladr_moscow_street_names.txt").read_text(
        encoding="utf-8"
    )
    assert checker.street_status("Хапиловский проезд").status is StreetStatusKind.KNOWN


def test_an_unknown_street_is_unknown() -> None:
    checker = FileTextChecker.load()
    assert checker is not None
    assert (
        checker.street_status("Улица Космических Пришельцев №1").status is StreetStatusKind.UNKNOWN
    )


def test_the_organizer_verbatim_ticket_spelling_is_flagged_never_corrected() -> None:
    """D-h: ticket-15-call-3's «ул. Зверенецкая» is not in the scenario data this test touches —
    only the directory's own reading of that exact string, which must be `NEAR`, never `KNOWN` (a
    silent match would be the same thing as a correction the report must never make)."""
    checker = FileTextChecker.load()
    assert checker is not None
    lookup = checker.street_status("ул. Зверенецкая")
    assert lookup.status is StreetStatusKind.NEAR
    assert "Зверинецкая улица" in lookup.suggestions


def test_the_data_sha_is_recorded_and_matches_the_files_on_disk() -> None:
    """§71.12's acceptance item: the data sha is recorded."""
    checker = FileTextChecker.load()
    assert checker is not None
    expected_dictionary = hashlib.sha256(
        (DEFAULT_LEXICON_DIR / "ru_RU.aff").read_bytes()
        + (DEFAULT_LEXICON_DIR / "ru_RU.dic").read_bytes()
    ).hexdigest()
    expected_streets = hashlib.sha256(
        (DEFAULT_STREETS_DIR / "osm_moscow_street_names.txt").read_bytes()
        + (DEFAULT_STREETS_DIR / "kladr_moscow_street_names.txt").read_bytes()
    ).hexdigest()
    assert checker.dictionary_sha256 == expected_dictionary
    assert checker.street_list_sha256 == expected_streets


def test_absent_lexicon_directory_is_none_never_raises(tmp_path: Path) -> None:
    """§71.12's acceptance item: with the data absent, there is no checker at all."""
    assert SpellingDictionary.load(tmp_path / "missing-lexicon") is None
    assert StreetDirectory.load(tmp_path / "missing-streets") is None
    assert FileTextChecker.load(tmp_path / "missing-lexicon", DEFAULT_STREETS_DIR) is None
    assert FileTextChecker.load(DEFAULT_LEXICON_DIR, tmp_path / "missing-streets") is None
    assert FileTextChecker.load(tmp_path / "a", tmp_path / "b") is None
