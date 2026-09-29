"""«Случайный порядок карточек» — a seeded card order (I7 E53, G12a; ТЗ ¶340 «Система формирует для
обучающегося случайную карточку»; HLD `71-i4-wave4.md` §71.19.53).

The seed is data (determinism rule 3, D7): the application draws it once when the lesson is
created, the plan is permuted **once**, and both the permuted plan and the seed are stored on the
lesson. Nothing reads the seed again to decide anything — a restart, a replay or a report reads the
stored plan, so they are unchanged by this module.

What moves and what stays. A plan position is a *slot* on the lesson's clock (its `arrival`) for a
set of workstations (its `participants`); a *card* is what fills it (`scenario_version_id`,
`variants`, `weight`, `timers`). The permutation moves cards between the slots of the **same
participant set**, so

* every trainee still gets exactly the cards the instructor ticked for them, in a random order
  («Раздать карточки» — one trainee per card — shuffles each trainee's own cards);
* a card ticked for everyone moves only among the other everyone-cards;
* position 1 keeps its `AT_OFFSET` arrival (`validate_plan`'s rule), whatever card lands there.

The draw is a Fisher-Yates over `sha256(f"{seed}:{set}:{i}")` rather than `random.shuffle`, so the
same seed gives the same order on every Python version.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.domain.lesson.plan import PlanEntry

__all__ = ["SHUFFLE_SEED_MAX", "shuffle_plan"]

SHUFFLE_SEED_MAX = 2**53 - 1
"""The largest seed: a JSON number a browser reads back exactly (`Number.MAX_SAFE_INTEGER`)."""

#: The card half of a `PlanEntry` — what the shuffle moves from one slot to another.
_CARD_FIELDS: tuple[str, ...] = ("scenario_version_id", "variants", "weight", "timers")


def _participant_set(entry: PlanEntry) -> str:
    """The slot's workstation set as a stable label (`*` = every lesson participant)."""
    if entry.participants is None:
        return "*"
    return ",".join(sorted(str(user_id) for user_id in entry.participants))


def _permutation(size: int, seed: int, label: str) -> list[int]:
    """A seeded Fisher-Yates permutation of `range(size)`."""
    order = list(range(size))
    for index in range(size - 1, 0, -1):
        digest = hashlib.sha256(f"{seed}:{label}:{index}".encode()).hexdigest()
        swap = int(digest, 16) % (index + 1)
        order[index], order[swap] = order[swap], order[index]
    return order


def shuffle_plan(entries: Sequence[PlanEntry], seed: int) -> tuple[PlanEntry, ...]:
    """`entries` with their cards permuted among the slots of each participant set, by `seed`.

    Positions, arrivals and participants stay where they are; the result is in `position` order.
    """
    ordered = sorted(entries, key=lambda entry: entry.position)
    slots_by_set: dict[str, list[PlanEntry]] = {}
    for entry in ordered:
        slots_by_set.setdefault(_participant_set(entry), []).append(entry)
    shuffled: dict[int, PlanEntry] = {}
    for label, slots in slots_by_set.items():
        order = _permutation(len(slots), seed, label)
        for slot, source_index in zip(slots, order, strict=True):
            card = slots[source_index]
            shuffled[slot.position] = slot.model_copy(
                update={name: getattr(card, name) for name in _CARD_FIELDS}
            )
    return tuple(shuffled[entry.position] for entry in ordered)
