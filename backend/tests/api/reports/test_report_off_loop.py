"""(I7 E57) A slow «Грамотность и адреса» check never stalls the event loop.

E57's finding: the text checker is CPU-bound pure Python (spylls suggestions, ~150 ms a misspelled
word), and it ran inside the async handler — every other request, a login included, waited until
the report was done. The report now runs the check on a worker thread (`asyncio.to_thread`).

This proves it over the real ASGI app: the checker is a stand-in whose every suggestion-bearing
call takes `_CALL_S` of wall time (a `time.sleep`, so the bound does not depend on how busy the
host's CPUs are under `-n 4`). While the report is still inside the checker, a `health/live`
request on the same event loop must come back within `_RESPONSIVE_S` — generous next to a direct
call's few milliseconds, and far below the several seconds the in-loop check would hold it.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Sequence

import pytest
from app.api.container import Container
from app.application.ports.text_checker import MisspelledSpan, StreetLookup, StreetStatusKind

from tests.api.reports.conftest import OperatorFlow, report

pytestmark = pytest.mark.integration

_CALL_S = 0.4
_RESPONSIVE_S = 0.5


class _SlowChecker:
    """Every check sleeps `_CALL_S` and flags nothing; counts the calls still running."""

    dictionary_sha256 = "dict-sha"
    street_list_sha256 = "streets-sha"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.running = 0
        self.finished = 0
        self._lock = threading.Lock()

    def _slow(self) -> None:
        with self._lock:
            self.running += 1
        self.started.set()
        time.sleep(_CALL_S)
        with self._lock:
            self.running -= 1
            self.finished += 1

    def misspellings(self, text: str, *, suggest: bool = True) -> Sequence[MisspelledSpan]:
        self._slow()
        return ()

    def street_status(
        self, street: str, locality: str | None = None, *, suggest: bool = True
    ) -> StreetLookup:
        self._slow()
        return StreetLookup(status=StreetStatusKind.KNOWN)


async def test_a_slow_text_check_leaves_the_event_loop_responsive(
    completed: OperatorFlow, container: Container
) -> None:
    checker = _SlowChecker()
    container.text_checker = checker

    pending = asyncio.create_task(report(completed))
    assert await asyncio.to_thread(checker.started.wait, 10), "the report never reached the check"
    # In the loop, the check would already be over by the time this task runs again.
    assert checker.running == 1, "the text check ran inside the event loop"

    started = time.monotonic()
    live = await completed.client.get("/api/v1/health/live")
    elapsed = time.monotonic() - started
    assert live.status_code == 200
    assert elapsed < _RESPONSIVE_S, f"health/live took {elapsed:.2f} s while the report ran"
    assert not pending.done(), "the report finished before the concurrent request was answered"

    response = await pending
    assert response.status_code == 200, response.text
    assert response.json()["text_quality"]["available"] is True
    assert checker.finished >= 2, "the demo card has more than one checked text"
