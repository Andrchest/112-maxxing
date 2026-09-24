"""`LessonRunner` — starts a lesson's cards by arrival (HLD 70 §70.3.3, D15, D7).

Beside `SimulationRunner` and with the same discipline:

* **one asyncio task per `ACTIVE` lesson**, ticking every `SIM_TICK_MS`;
* **a Redis lock** `lock:lesson:{id}:runner` (`LessonRunnerLock`) taken before the first tick and
  refreshed every `lock_refresh_s`; an instance that loses it stops ticking that lesson;
* **re-adoption**: `start()` adopts every `ACTIVE` lesson in PostgreSQL, so a backend restart
  resumes every running lesson — arrivals are measured against the persisted `started_at`, never
  a process clock;
* **one lesson's failure never reaches another's**, and `stop()` cancels and awaits every task and
  releases every lock it holds.

**One tick.** In `position` order, for each plan entry whose session is still `READY`: evaluate
its `Arrival` against the lesson's wall clock (`app.domain.lesson.plan.arrival_holds`); when it
holds, call the existing `startSession` **as the instructor who created the lesson**
(`ActorRef(INSTRUCTOR, created_by_user_id)` — the closest true actor, the reading
`prefab_handoff.py` uses), so `SESSION_TRANSITIONS`' `READY --start--> ACTIVE (INSTRUCTOR)` row is
untouched. The arrival is recorded in `SESSION_STARTED.lesson_arrival {kind, due_offset_ms,
fired_offset_ms}`. `503 INFERENCE_NOT_READY` is retried next tick and appends nothing. A started
card is handed to `on_session_started` — the composition root adopts it into the
`SimulationRunner`, which runs it exactly as any other session: N cards, N session runners. When
every card is `COMPLETED` or `ABORTED`, the tick fires the lesson's `complete` (SYSTEM) and the
task ends.

**What the `AFTER_*` arrivals read** (`PreviousCard`, lesson wall ms, from the previous card's
log — its `timestamp_utc`s against the lesson's `started_at`):

* `AFTER_PREVIOUS_112_STAGE` — the previous card's `STAGE_STATE_CHANGED` of its OPERATOR_112 stage
  to `HANDED_OFF`; a card without a 112 stage (`GENERATED_CARD`) is handed off when its prefab is
  received (`HANDOFF_RECEIVED`); a card that ended without ever handing off counts from its end,
  so the next card is never stranded;
* `AFTER_PREVIOUS_SESSION` — its `SESSION_COMPLETED` or `SESSION_ABORTED`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import NamedTuple

from app.application.lessons.errors import TERMINAL_SESSION_STATES
from app.application.ports.clock import Clock
from app.application.ports.lesson_repository import StoredLessonCard
from app.application.ports.runner_lock import LessonRunnerLock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.start_session import InferenceNotReadyError, StartSession
from app.application.timebase import session_offset_ms
from app.domain.common.actors import ActorRef
from app.domain.common.errors import InvalidTransitionError
from app.domain.common.ids import LessonId, SessionId
from app.domain.enums import ActorType, Operator112StageState, RoleType, SessionState
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.lesson.lesson import Lesson, LessonState
from app.domain.lesson.plan import PreviousCard, arrival_due_offset_ms

__all__ = ["LessonRunner", "LessonTickResult", "previous_card_facts"]

logger = logging.getLogger(__name__)

_SYSTEM = ActorRef(actor_type=ActorType.SYSTEM)


class LessonTickResult(NamedTuple):
    """What one lesson tick did."""

    started: tuple[SessionId, ...] = ()
    completed: bool = False
    finished: bool = False
    """The lesson is no longer `ACTIVE` (completed now, earlier, or aborted): stop ticking it."""


class _DueCard(NamedTuple):
    card: StoredLessonCard
    arrival: dict[str, object]


def previous_card_facts(
    events: Sequence[SessionEvent], lesson_started_at: datetime
) -> PreviousCard:
    """`PreviousCard` from the previous card's log, in lesson wall ms (see the module docstring)."""

    def at(event: SessionEvent) -> int:
        return session_offset_ms(event.timestamp_utc, lesson_started_at)

    handed_off: int | None = None
    ended: int | None = None
    for event in events:
        if handed_off is None and _is_handoff(event):
            handed_off = at(event)
        if ended is None and event.event_type in (
            EventType.SESSION_COMPLETED,
            EventType.SESSION_ABORTED,
        ):
            ended = at(event)
    return PreviousCard(
        handed_off_at_ms=handed_off if handed_off is not None else ended, ended_at_ms=ended
    )


def _is_handoff(event: SessionEvent) -> bool:
    if event.event_type is EventType.HANDOFF_RECEIVED:
        return True
    return (
        event.event_type is EventType.STAGE_STATE_CHANGED
        and event.payload.get("role_type") == RoleType.OPERATOR_112.value
        and event.payload.get("new_state") == Operator112StageState.HANDED_OFF.value
    )


class LessonRunner:
    """One asyncio task per adopted lesson, each starting cards by arrival."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        start_session: StartSession,
        lock: LessonRunnerLock,
        clock: Clock,
        *,
        instance_id: str,
        tick_ms: int,
        lock_ttl_s: int,
        lock_refresh_s: int,
        on_session_started: Callable[[SessionId], None] | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._start_session = start_session
        self._lock = lock
        self._clock = clock
        self._instance_id = instance_id
        self._tick_ms = tick_ms
        self._lock_ttl_s = lock_ttl_s
        self._lock_refresh_s = lock_refresh_s
        self._on_session_started = on_session_started
        self._tasks: dict[LessonId, asyncio.Task[None]] = {}
        self._held: set[LessonId] = set()
        self._stopping = False

    # -- lifecycle -----------------------------------------------------------------------------

    async def start(self) -> list[LessonId]:
        """Re-adopt every `ACTIVE` lesson from PostgreSQL; returns the ids adopted."""
        self._stopping = False
        async with self._unit_of_work() as uow:
            lesson_ids = await uow.lessons.list_active_lesson_ids()
            await uow.commit()
        for lesson_id in lesson_ids:
            self.adopt(lesson_id)
        return lesson_ids

    def adopt(self, lesson_id: LessonId) -> None:
        """Start this lesson's tick task; adopting an adopted lesson is a no-op."""
        if self._stopping or lesson_id in self._tasks:
            return
        self._tasks[lesson_id] = asyncio.create_task(
            self._run(lesson_id), name=f"lesson-runner:{lesson_id}"
        )

    async def release(self, lesson_id: LessonId) -> None:
        """Stop ticking this lesson and give up its lock."""
        task = self._tasks.pop(lesson_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._release_lock(lesson_id)

    async def stop(self) -> None:
        """Cancel and await every task, then release every lock this instance still holds."""
        self._stopping = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for lesson_id in list(self._held):
            await self._release_lock(lesson_id)

    @property
    def adopted(self) -> frozenset[LessonId]:
        return frozenset(self._tasks)

    @property
    def held_locks(self) -> frozenset[LessonId]:
        return frozenset(self._held)

    # -- ticking -------------------------------------------------------------------------------

    async def tick_now(self, lesson_id: LessonId) -> LessonTickResult:
        """Tick once, immediately (after `startLesson`, and in tests); no lock needed — the
        session row locks serialise the starts, and `start` refuses a session that is not
        `READY`, so a doubled tick starts nothing twice."""
        due, lesson = await self._due_cards(lesson_id)
        if lesson is None:
            return LessonTickResult(finished=True)
        started: list[SessionId] = []
        creator = ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=lesson.created_by_user_id)
        for item in due:
            try:
                await self._start_session(
                    item.card.session_id, creator, lesson_arrival=item.arrival
                )
            except InferenceNotReadyError:
                logger.info(
                    "lesson %s card %d: inference not ready; retried next tick",
                    lesson_id,
                    item.card.position,
                )
                continue
            except InvalidTransitionError:
                # The card left READY under us (aborted, or started by a concurrent tick).
                continue
            started.append(item.card.session_id)
            if self._on_session_started is not None:
                self._on_session_started(item.card.session_id)
        completed, finished = await self._complete_if_done(lesson_id)
        return LessonTickResult(started=tuple(started), completed=completed, finished=finished)

    async def _due_cards(self, lesson_id: LessonId) -> tuple[list[_DueCard], Lesson | None]:
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get(lesson_id)
            if lesson is None or lesson.state is not LessonState.ACTIVE:
                await uow.commit()
                return [], None
            assert lesson.started_at is not None  # `start` sets it
            cards = await uow.lessons.list_cards(lesson_id)
            now_ms = session_offset_ms(self._clock.now(), lesson.started_at)
            due: list[_DueCard] = []
            by_position = {card.position: card for card in cards}
            for card in cards:
                if card.state is not SessionState.READY:
                    continue
                arrival = lesson.entry(card.position).arrival
                previous = await self._previous(uow, by_position.get(card.position - 1), lesson)
                due_ms = arrival_due_offset_ms(arrival, previous)
                if due_ms is None or now_ms < due_ms:
                    continue
                due.append(
                    _DueCard(
                        card,
                        {
                            "kind": arrival.kind.value,
                            "due_offset_ms": due_ms,
                            "fired_offset_ms": now_ms,
                        },
                    )
                )
            await uow.commit()
        return due, lesson

    async def _previous(
        self, uow: UnitOfWork, card: StoredLessonCard | None, lesson: Lesson
    ) -> PreviousCard | None:
        if card is None:
            return None
        if card.state in (SessionState.CREATED, SessionState.READY):
            return PreviousCard()
        assert lesson.started_at is not None
        return previous_card_facts(await uow.events.read(card.session_id), lesson.started_at)

    async def _complete_if_done(self, lesson_id: LessonId) -> tuple[bool, bool]:
        """Fire `complete` (SYSTEM) once every card is terminal.

        Returns `(completed_now, finished)`: `finished` is also true for a lesson that is no
        longer `ACTIVE` for any other reason (aborted meanwhile, or gone)."""
        async with self._unit_of_work() as uow:
            lesson = await uow.lessons.get_for_update(lesson_id)
            if lesson is None or lesson.state is not LessonState.ACTIVE:
                await uow.commit()
                return False, True
            states = [card.state for card in await uow.lessons.list_cards(lesson_id)]
            if not states or not all(state in TERMINAL_SESSION_STATES for state in states):
                await uow.commit()
                return False, False
            completed = lesson.complete(
                self._clock.now(), actor=_SYSTEM, plan_session_states=states
            )
            await uow.lessons.save(completed)
            await uow.commit()
        return True, True

    async def _run(self, lesson_id: LessonId) -> None:
        """One lesson's loop: acquire, then tick every `tick_ms` while the lock is held."""
        interval = self._tick_ms / 1000
        if not await self._acquire(lesson_id):
            logger.info("lesson %s is already run by another instance; not adopting", lesson_id)
            self._tasks.pop(lesson_id, None)
            return
        elapsed = 0.0
        try:
            while True:
                try:
                    result = await self.tick_now(lesson_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("tick of lesson %s failed; the loop continues", lesson_id)
                    result = LessonTickResult()
                if result.finished:
                    break
                await asyncio.sleep(interval)
                elapsed += interval
                if elapsed >= self._lock_refresh_s:
                    elapsed = 0.0
                    if not await self._refresh(lesson_id):
                        logger.warning("lesson %s: runner lock lost; stop ticking it", lesson_id)
                        return
        finally:
            if self._tasks.get(lesson_id) is asyncio.current_task():
                self._tasks.pop(lesson_id, None)
                await self._release_lock(lesson_id)

    # -- lock ----------------------------------------------------------------------------------

    async def _acquire(self, lesson_id: LessonId) -> bool:
        taken = await self._lock.acquire(lesson_id, self._instance_id, self._lock_ttl_s)
        if taken:
            self._held.add(lesson_id)
        return taken

    async def _refresh(self, lesson_id: LessonId) -> bool:
        held = await self._lock.refresh(lesson_id, self._instance_id, self._lock_ttl_s)
        if not held:
            self._held.discard(lesson_id)
        return held

    async def _release_lock(self, lesson_id: LessonId) -> None:
        if lesson_id not in self._held:
            return
        self._held.discard(lesson_id)
        try:
            await self._lock.release(lesson_id, self._instance_id)
        except Exception:  # Redis is non-authoritative (§40.6); the TTL frees the key anyway
            logger.exception("releasing the runner lock of lesson %s failed", lesson_id)
