"""`LessonRepository` port — the `lessons` table and the lesson's view of its sessions (HLD 70
§70.3, §70.8 `0011_lessons`, D15).

A lesson is scheduling, not simulation: its row carries the plan and four timestamps, and its
cards are ordinary `simulation_sessions` rows pointing back at it (`lesson_id`,
`lesson_position`). `get_for_update` takes the row lock the `LessonRunner` and the lesson commands
serialise on, exactly as `SessionRepository.get_for_update` does for a session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.domain.common.ids import IncidentId, LessonId, SessionId, UserId
from app.domain.dds.card_status import CardStatus
from app.domain.enums import SessionMode, SessionState
from app.domain.lesson.lesson import Lesson, LessonState

__all__ = ["LessonRepository", "StoredLessonCard", "StoredLessonListing"]


class StoredLessonListing(BaseModel):
    """One row of `listLessons` — `LessonListItem`, property names literal."""

    model_config = ConfigDict(frozen=True)

    lesson_id: LessonId
    title_ru: str
    session_mode: SessionMode
    state: LessonState
    card_count: int
    created_at: datetime
    created_by_user_id: UserId


class StoredLessonCard(BaseModel):
    """One plan session as the lesson sees it: the session row, its incident's read model."""

    model_config = ConfigDict(frozen=True)

    position: int
    session_id: SessionId
    incident_id: IncidentId
    display_number: int
    state: SessionState
    card_status: CardStatus
    started_at: datetime | None
    completed_at: datetime | None


@runtime_checkable
class LessonRepository(Protocol):
    """Read and write lessons (§70.8)."""

    async def add(self, lesson: Lesson) -> None:
        """Insert a brand-new lesson (before its sessions, which reference it)."""
        ...

    async def get(self, lesson_id: LessonId) -> Lesson | None:
        """The lesson, or `None`; no row lock."""
        ...

    async def get_for_update(self, lesson_id: LessonId) -> Lesson | None:
        """The lesson under a row lock held for the rest of the transaction."""
        ...

    async def save(self, lesson: Lesson) -> None:
        """Write back the mutable columns: state, the four timestamps, the release author."""
        ...

    async def save_weights(self, lesson: Lesson) -> None:
        """Write back `scenario_plan` (its weights) and `weight_proposals` (I3 E9a, §70.3.7).

        The only writer of the plan after creation: `acceptWeightProposals` changes weights and
        nothing else of an entry.
        """
        ...

    async def list_lessons(
        self,
        *,
        viewer_user_id: UserId,
        mine_only: bool,
        state: LessonState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredLessonListing], int]:
        """One page of lessons, newest first, plus the unpaged total.

        `mine_only`: the lessons the viewer created or is a participant of.
        """
        ...

    async def list_active_lesson_ids(self) -> list[LessonId]:
        """Every `ACTIVE` lesson's id — the `LessonRunner`'s adoption read (§70.3.3)."""
        ...

    async def list_cards(self, lesson_id: LessonId) -> list[StoredLessonCard]:
        """The lesson's sessions in `position` order."""
        ...
