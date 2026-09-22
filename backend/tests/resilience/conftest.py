"""Shared assertion for the SPEC §39 suite: "never silently reset the simulation" (§39's closing
line). It applies to all six numbered behaviours and is asserted inside each of their tests rather
than getting a test of its own.

Every behaviour's seam produces some ordered, append-only record — a `session_events` log read
back over real HTTP (module 1), an in-memory `VoiceStore`/`DialogueStore`'s `.events` (modules
2-4), or whatever module 5/6 add. Whatever the record is, "never silently reset" reduces to the
same shape: nothing already written disappears, and nothing already written is rewritten. That
shape is `assert_prefix_preserved` below — the one place all six modules can share it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = ["assert_prefix_preserved"]


def assert_prefix_preserved(before: Sequence[Any], after: Sequence[Any]) -> None:
    """`after` must start with exactly `before` (`==`, elementwise, in order).

    A failure is free to *append* — a new `MODEL_ERROR`, a new fallback event, whatever the
    behaviour's own mechanism produces — but never to drop or overwrite a record that already
    existed before the failure. `len(before) <= len(after)` is the "event count before <= after"
    half of the brief's phrasing; the elementwise equality is the "nothing rewritten" half.
    """
    assert len(after) >= len(before), (
        f"{len(before) - len(after)} record(s) disappeared — the simulation was silently reset"
    )
    assert list(after[: len(before)]) == list(before), (
        "an existing record changed — the simulation was silently reset"
    )
