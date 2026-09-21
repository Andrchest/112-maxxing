"""`rng_for` — determinism rule 3 (HLD §10.11, D7, SPEC §42 item 7)."""

from __future__ import annotations

import hashlib
from random import Random

from app.domain.world.rng import rng_for

SEED = "apartment-fire-v1"


def test_factory_reproduces_the_documented_formula() -> None:
    digest = hashlib.sha256(f"{SEED}:ac2_breakdown:0".encode()).hexdigest()
    assert rng_for(SEED)("ac2_breakdown", 0).random() == Random(digest).random()


def test_golden_values_are_pinned() -> None:
    """Three pinned draws: a regression here means the seed formula changed."""
    factory = rng_for(SEED)
    assert factory("ac2_breakdown", 0).random() == 0.1453264869348364
    assert factory("ac2_breakdown", 1).random() == 0.844452644121652
    assert factory("fire_spreads", 0).random() == 0.0172972070873042


def test_draw_is_stable_across_calls_and_independent_of_order() -> None:
    factory = rng_for(SEED)
    first = factory("ac2_breakdown", 0).random()
    factory("fire_spreads", 7).random()
    factory("ac2_breakdown", 3).random()
    assert factory("ac2_breakdown", 0).random() == first


def test_seed_event_id_and_occurrence_all_matter() -> None:
    base = rng_for(SEED)("ac2_breakdown", 0).random()
    assert rng_for("other-seed")("ac2_breakdown", 0).random() != base
    assert rng_for(SEED)("other_event", 0).random() != base
    assert rng_for(SEED)("ac2_breakdown", 1).random() != base
