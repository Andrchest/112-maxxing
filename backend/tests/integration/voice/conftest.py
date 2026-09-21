"""Fixtures for the voice integration tests (real PostgreSQL).

They are the persistence package's, re-exported rather than re-written: the `audio_segments` row
and the `session_events` row this package is about must commit through the *same* Unit of Work
the rest of the system uses (§9.1's ordering guarantee, D5), so reproducing a second setup here
would be reproducing the wrong thing.
"""

from __future__ import annotations

from tests.integration.persistence.conftest import (  # noqa: F401
    clean_database,
    clock,
    publisher,
    seeded,
    session_factory,
    session_id,
    unit_of_work,
)
