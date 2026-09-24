"""`SqlAlchemyLessonRepository` — lessons over PostgreSQL (HLD 70 §70.3, §70.8 `0011_lessons`).

The row is the aggregate: `participants`, `scenario_plan` and `variants` are jsonb documents of the
plan's own types, written and read whole. The lesson's cards are ordinary `simulation_sessions`
rows (`lesson_id`, `lesson_position`); `list_cards` joins them with their incident's read model.
`get_for_update` takes `FOR NO KEY UPDATE`, the one row-lock mode every writer uses (the
`SqlAlchemyEventStore` docstring, R14).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.lesson_repository import StoredLessonCard, StoredLessonListing
from app.db.models.session import Incident as IncidentRow
from app.db.models.session import Lesson as LessonRow
from app.db.models.session import SimulationSession as SessionRow
from app.domain.common.ids import IncidentId, LessonId, SessionId, TraineeGroupId, UserId
from app.domain.dds.card_status import CardStatus
from app.domain.enums import SessionMode, SessionState
from app.domain.lesson.lesson import Lesson, LessonState
from app.domain.lesson.plan import LessonParticipant, PlanEntry
from app.domain.lesson.weights import WeightProposalSet
from app.domain.session.variants import PartialVariants

__all__ = ["SqlAlchemyLessonRepository", "lesson_from_row", "lesson_row_values"]

_LESSONS = LessonRow.__table__
_SESSIONS = SessionRow.__table__
_INCIDENTS = IncidentRow.__table__

#: Columns an UPDATE may change; the plan, the participants and the title are fixed at creation
#: (the plan's weights excepted — `save_weights`, I3 E9a).
_MUTABLE_COLUMNS: tuple[str, ...] = (
    "state",
    "started_at",
    "completed_at",
    "report_released_at",
    "report_released_by_user_id",
)


def _variants_document(variants: PartialVariants) -> dict[str, str]:
    """A `VariantsRequest` document: only the switches the request names."""
    return {key: value for key, value in variants.model_dump(mode="json").items() if value}


def _plan_document(lesson: Lesson) -> list[dict[str, Any]]:
    return [
        {
            **entry.model_dump(mode="json", exclude={"variants"}),
            "variants": (None if entry.variants is None else _variants_document(entry.variants)),
        }
        for entry in lesson.scenario_plan
    ]


def _proposals_document(lesson: Lesson) -> Any:
    """The proposal set's document, or SQL `NULL` (not the JSON `null` a bare `None` writes)."""
    proposals = lesson.weight_proposals
    return sa.null() if proposals is None else proposals.model_dump(mode="json")


def lesson_row_values(lesson: Lesson) -> dict[str, Any]:
    """Column values for one `lessons` row."""
    return {
        "id": UUID(str(lesson.lesson_id)),
        "title_ru": lesson.title_ru,
        "created_by_user_id": UUID(str(lesson.created_by_user_id)),
        "session_mode": lesson.session_mode.value,
        "variants": _variants_document(lesson.variants),
        "participants": [
            participant.model_dump(mode="json") for participant in lesson.participants
        ],
        "scenario_plan": _plan_document(lesson),
        "state": lesson.state.value,
        "created_at": lesson.created_at,
        "started_at": lesson.started_at,
        "completed_at": lesson.completed_at,
        "report_released_at": lesson.report_released_at,
        "report_released_by_user_id": (
            None
            if lesson.report_released_by_user_id is None
            else UUID(str(lesson.report_released_by_user_id))
        ),
        "group_id": None if lesson.group_id is None else UUID(str(lesson.group_id)),
        "weight_proposals": _proposals_document(lesson),
    }


def lesson_from_row(row: Mapping[str, Any]) -> Lesson:
    """Read one `lessons` row back into the aggregate."""
    released_by = row["report_released_by_user_id"]
    group_id = row["group_id"]
    proposals = row["weight_proposals"]
    return Lesson(
        lesson_id=LessonId(UUID(str(row["id"]))),
        title_ru=str(row["title_ru"]),
        created_by_user_id=UserId(UUID(str(row["created_by_user_id"]))),
        session_mode=SessionMode(str(row["session_mode"])),
        variants=PartialVariants.model_validate(row["variants"] or {}),
        participants=tuple(
            LessonParticipant.model_validate(item) for item in row["participants"] or []
        ),
        scenario_plan=tuple(PlanEntry.model_validate(item) for item in row["scenario_plan"] or []),
        state=LessonState(str(row["state"])),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        report_released_at=row["report_released_at"],
        report_released_by_user_id=(
            None if released_by is None else UserId(UUID(str(released_by)))
        ),
        group_id=None if group_id is None else TraineeGroupId(UUID(str(group_id))),
        weight_proposals=(
            None if proposals is None else WeightProposalSet.model_validate(proposals)
        ),
    )


class SqlAlchemyLessonRepository:
    """`LessonRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, lesson: Lesson) -> None:
        await self._session.execute(sa.insert(_LESSONS).values(**lesson_row_values(lesson)))

    async def get(self, lesson_id: LessonId) -> Lesson | None:
        return await self._load(lesson_id, for_update=False)

    async def get_for_update(self, lesson_id: LessonId) -> Lesson | None:
        return await self._load(lesson_id, for_update=True)

    async def save(self, lesson: Lesson) -> None:
        values = lesson_row_values(lesson)
        await self._session.execute(
            sa.update(_LESSONS)
            .where(_LESSONS.c.id == UUID(str(lesson.lesson_id)))
            .values(**{column: values[column] for column in _MUTABLE_COLUMNS})
        )

    async def save_weights(self, lesson: Lesson) -> None:
        await self._session.execute(
            sa.update(_LESSONS)
            .where(_LESSONS.c.id == UUID(str(lesson.lesson_id)))
            .values(
                scenario_plan=_plan_document(lesson),
                weight_proposals=_proposals_document(lesson),
            )
        )

    async def list_lessons(
        self,
        *,
        viewer_user_id: UserId,
        mine_only: bool,
        state: LessonState | None,
        limit: int,
        offset: int,
    ) -> tuple[list[StoredLessonListing], int]:
        viewer = UUID(str(viewer_user_id))
        conditions: list[sa.ColumnElement[bool]] = []
        if state is not None:
            conditions.append(_LESSONS.c.state == state.value)
        if mine_only:
            conditions.append(
                sa.or_(
                    _LESSONS.c.created_by_user_id == viewer,
                    _LESSONS.c.participants.contains([{"user_id": str(viewer)}]),
                )
            )
        total = int(
            (
                await self._session.execute(
                    sa.select(sa.func.count()).select_from(_LESSONS).where(*conditions)
                )
            ).scalar_one()
        )
        result = await self._session.execute(
            sa.select(
                _LESSONS.c.id,
                _LESSONS.c.title_ru,
                _LESSONS.c.session_mode,
                _LESSONS.c.state,
                _LESSONS.c.created_at,
                _LESSONS.c.created_by_user_id,
                sa.func.jsonb_array_length(_LESSONS.c.scenario_plan).label("card_count"),
            )
            .where(*conditions)
            .order_by(_LESSONS.c.created_at.desc(), _LESSONS.c.id)
            .limit(limit)
            .offset(offset)
        )
        items = [
            StoredLessonListing(
                lesson_id=LessonId(UUID(str(row.id))),
                title_ru=str(row.title_ru),
                session_mode=SessionMode(str(row.session_mode)),
                state=LessonState(str(row.state)),
                card_count=int(row.card_count),
                created_at=row.created_at,
                created_by_user_id=UserId(UUID(str(row.created_by_user_id))),
            )
            for row in result.all()
        ]
        return items, total

    async def list_active_lesson_ids(self) -> list[LessonId]:
        result = await self._session.execute(
            sa.select(_LESSONS.c.id)
            .where(_LESSONS.c.state == LessonState.ACTIVE.value)
            .order_by(_LESSONS.c.id)
        )
        return [LessonId(UUID(str(row[0]))) for row in result.all()]

    async def list_cards(self, lesson_id: LessonId) -> list[StoredLessonCard]:
        result = await self._session.execute(
            sa.select(
                _SESSIONS.c.id,
                _SESSIONS.c.lesson_position,
                _SESSIONS.c.state,
                _SESSIONS.c.started_at,
                _SESSIONS.c.completed_at,
                _INCIDENTS.c.id.label("incident_id"),
                _INCIDENTS.c.display_number,
                _INCIDENTS.c.card_status,
            )
            .select_from(_SESSIONS.join(_INCIDENTS, _INCIDENTS.c.session_id == _SESSIONS.c.id))
            .where(_SESSIONS.c.lesson_id == UUID(str(lesson_id)))
            .order_by(_SESSIONS.c.lesson_position)
        )
        return [
            StoredLessonCard(
                position=int(row.lesson_position),
                session_id=SessionId(UUID(str(row.id))),
                incident_id=IncidentId(UUID(str(row.incident_id))),
                display_number=int(row.display_number),
                state=SessionState(str(row.state)),
                card_status=CardStatus(str(row.card_status)),
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in result.all()
        ]

    async def _load(self, lesson_id: LessonId, *, for_update: bool) -> Lesson | None:
        statement = sa.select(_LESSONS).where(_LESSONS.c.id == UUID(str(lesson_id)))
        if for_update:
            statement = statement.with_for_update(key_share=True)
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else lesson_from_row(row._mapping)
