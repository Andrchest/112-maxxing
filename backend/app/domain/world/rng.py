"""`rng_for` — the seeded RNG factory of determinism rule 3 (HLD `10-domain-model.md` §10.11, D7).

The whole engine's randomness enters through this one function. `rng_for(session_seed)` returns
the factory §10.11 rule 3 prints literally::

    rng_factory(event_id, occurrence) ->
        Random(sha256(f"{session_seed}:{event_id}:{occurrence}".encode()).hexdigest())

The seed of a draw therefore depends only on `(session_seed, event_id, occurrence)` — never on
evaluation order, the wall clock, the tick partition or the number of previous draws (D7), which
is exactly what SPEC §42 item 7 ("identical seed and actions produce identical deterministic world
events") needs. `engine.advance` passes an absolute *draw index* inside the `event_id` argument
for `SeededRandomEvent` check ticks; see `engine.py`'s module docstring.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from random import Random

__all__ = ["rng_for"]


def rng_for(session_seed: str) -> Callable[[str, int], Random]:
    """Return the `(event_id, occurrence) -> random.Random` factory for `session_seed` (rule 3)."""

    def factory(event_id: str, occurrence: int) -> Random:
        digest = hashlib.sha256(f"{session_seed}:{event_id}:{occurrence}".encode()).hexdigest()
        return Random(digest)

    return factory
