"""`lessons` and `incidents` schemas (`openapi.yaml`, HLD 70 §70.3, I3 E4a).

The wire models of `createLesson`, `listLessons`, `getLesson`, `startLesson`, `abortLesson`,
`getLessonReport`, `releaseLessonReport` and `listMyIncidents`, property names copied literally
from `docs/hld/contracts/i3-openapi-delta.yaml`. The mapping functions at the bottom are the only
bridge between the application views and the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.reports import (
    PassVerdictViewSchema,
    ScoreReportViewSchema,
    TextQualityReportViewSchema,
    TimelineEntryViewSchema,
    pass_verdict_schema,
    score_report_view_schema,
    text_quality_report_schema,
    timeline_entry_schema,
)
from app.api.schemas.sessions import (
    CardTimersRequestSchema,
    ParticipantAssignmentSchema,
    PassCriteriaRequestSchema,
    SessionVariantsSchema,
    VariantsRequestSchema,
)
from app.api.schemas.statistics import (
    LegReactionTimeViewSchema,
    NormViewSchema,
    leg_reaction_time_schema,
    norm_view_schema,
)
from app.api.schemas.typical_errors import TypicalErrorsSchema, typical_errors_schema
from app.application.lessons.lesson_report import LessonReportView
from app.application.lessons.queries import IncidentListItemView, LessonDetailView
from app.application.lessons.weight_proposals import WeightProposalsView
from app.application.ports.lesson_repository import StoredLessonListing
from app.application.reports.assemble_report import UnscoredSessionView
from app.domain.common.ids import ScenarioVersionId, TraineeGroupId, UserId
from app.domain.dds.card_status import CardStatus
from app.domain.dds.response import ServiceResponseStatus
from app.domain.enums import RoleType, ServiceId, SessionMode, SessionState
from app.domain.lesson.lesson import LessonState
from app.domain.lesson.plan import Arrival, ArrivalKind, LessonParticipant, PlanEntry
from app.domain.lesson.weights import MAX_PROPOSED_WEIGHT, MIN_PROPOSED_WEIGHT, ProposalSource

__all__ = [
    "ArrivalSchema",
    "IncidentListItemSchema",
    "LessonCreateRequestSchema",
    "LessonDetailSchema",
    "LessonListItemSchema",
    "LessonReportCardSchema",
    "LessonReportSchema",
    "LessonSessionViewSchema",
    "PlanEntrySchema",
    "UnscoredCardTimesSchema",
    "UnscoredCardViewSchema",
    "WeightProposalAcceptRequestSchema",
    "WeightProposalLineSchema",
    "WeightProposalSetSchema",
    "incident_list_item_schema",
    "lesson_detail_schema",
    "lesson_list_item_schema",
    "lesson_report_schema",
    "weight_proposal_set_schema",
]


class ArrivalSchema(ApiModel):
    """`Arrival` — `offset_ms` required for `AT_OFFSET`, forbidden otherwise (checked by the
    domain model, `422` either way)."""

    kind: ArrivalKind
    offset_ms: int | None = Field(default=None, ge=0)
    delay_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _offset_only_for_at_offset(self) -> Self:
        if (self.kind is ArrivalKind.AT_OFFSET) != (self.offset_ms is not None):
            raise ValueError("offset_ms is required for AT_OFFSET and forbidden otherwise")
        return self

    def to_domain(self) -> Arrival:
        return Arrival(kind=self.kind, offset_ms=self.offset_ms, delay_ms=self.delay_ms)

    @classmethod
    def of(cls, arrival: Arrival) -> ArrivalSchema:
        return cls(kind=arrival.kind, offset_ms=arrival.offset_ms, delay_ms=arrival.delay_ms)


class PlanEntrySchema(ApiModel):
    """`PlanEntry`."""

    position: int = Field(ge=1)
    scenario_version_id: UUID
    arrival: ArrivalSchema
    variants: VariantsRequestSchema | None = None
    participants: list[UUID] | None = None
    weight: float = Field(default=1.0, gt=0)
    timers: CardTimersRequestSchema | None = None
    """(additive, I4 E31) Per-card timer override, resolved as scenario ← this entry."""

    def to_domain(self) -> PlanEntry:
        return PlanEntry(
            position=self.position,
            scenario_version_id=ScenarioVersionId(self.scenario_version_id),
            arrival=self.arrival.to_domain(),
            variants=None if self.variants is None else self.variants.to_domain(),
            participants=(
                None
                if self.participants is None
                else tuple(UserId(user_id) for user_id in self.participants)
            ),
            weight=self.weight,
            timers=None if self.timers is None else self.timers.to_domain(),
        )

    @classmethod
    def of(cls, entry: PlanEntry) -> PlanEntrySchema:
        variants = entry.variants
        return cls(
            position=entry.position,
            scenario_version_id=UUID(str(entry.scenario_version_id)),
            arrival=ArrivalSchema.of(entry.arrival),
            variants=(
                None
                if variants is None
                else VariantsRequestSchema(
                    card_source=variants.card_source,
                    dds_mode=variants.dds_mode,
                    dds_card_check=variants.dds_card_check,
                    dds_brigade_call=variants.dds_brigade_call,
                )
            ),
            participants=(
                None
                if entry.participants is None
                else [UUID(str(user_id)) for user_id in entry.participants]
            ),
            weight=entry.weight,
            timers=None if entry.timers is None else CardTimersRequestSchema.of(entry.timers),
        )


class LessonCreateRequestSchema(ApiModel):
    """`LessonCreateRequest`."""

    title_ru: str = Field(min_length=1)
    session_mode: SessionMode
    participants: list[ParticipantAssignmentSchema] = Field(min_length=1)
    variants: VariantsRequestSchema | None = None
    scenario_plan: list[PlanEntrySchema] = Field(min_length=1)
    time_scale: float = Field(default=1.0, ge=0.1, le=10)
    group_id: UUID | None = None
    """I3 E9a: the trainee group the lesson is created for (recorded; `404` when unknown)."""
    pass_criteria: PassCriteriaRequestSchema | None = None
    """(additive, I5 E38) «Сдал / не сдал» for every card; absent = the defaults."""
    shuffle: bool = False
    """(additive, I7 E53) «Случайный порядок карточек»: the server draws a seed and permutes the
    plan's cards once; `LessonDetail.shuffle_seed` records it."""

    def domain_group_id(self) -> TraineeGroupId | None:
        return None if self.group_id is None else TraineeGroupId(self.group_id)

    def domain_participants(self) -> tuple[LessonParticipant, ...]:
        return tuple(
            LessonParticipant(
                user_id=UserId(assignment.user_id),
                assigned_role_type=assignment.assigned_role_type,
                assigned_service_id=(
                    None
                    if assignment.assigned_service_id is None
                    else ServiceId(assignment.assigned_service_id)
                ),
            )
            for assignment in self.participants
        )


class LessonSessionViewSchema(ApiModel):
    """`LessonSessionView`."""

    position: int = Field(ge=1)
    session_id: UUID
    incident_id: UUID
    display_number: int
    state: SessionState
    card_status: CardStatus
    arrival: ArrivalSchema
    started_at_lesson_offset_ms: int | None = None
    variants: SessionVariantsSchema


class LessonListItemSchema(ApiModel):
    """`LessonListItem`."""

    lesson_id: UUID
    title_ru: str
    session_mode: SessionMode
    state: LessonState
    card_count: int = Field(ge=1)
    created_at: datetime
    created_by_user_id: UUID


class LessonDetailSchema(ApiModel):
    """`LessonDetail`."""

    lesson_id: UUID
    title_ru: str
    session_mode: SessionMode
    state: LessonState
    participants: list[ParticipantAssignmentSchema]
    scenario_plan: list[PlanEntrySchema]
    sessions: list[LessonSessionViewSchema]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    report_released_at: datetime | None
    group_id: UUID | None
    # (additive, I5 E39, Q-E9b-4 а) the lesson's owner: only this instructor (or an ADMIN) may
    # change it; the UI disables the controls for everyone else.
    created_by_user_id: UUID
    # (additive, I7 E53) the seed the plan's cards were permuted with at creation; `null` = the
    # instructor's own order («Случайный порядок карточек» not ticked).
    shuffle_seed: int | None = None


class UnscoredCardTimesSchema(ApiModel):
    """`UnscoredCardView.times` (I4 E31)."""

    started_at: datetime | None
    aborted_at: datetime | None
    elapsed_ms: int | None = Field(ge=0)


class UnscoredCardViewSchema(ApiModel):
    """`UnscoredCardView` (I4 E31, HLD 71 §71.8): an ABORTED card of the lesson — actions and
    times, no points (Q-E9b-6)."""

    state: SessionState
    timeline: list[TimelineEntryViewSchema]
    times: UnscoredCardTimesSchema


class LessonReportCardSchema(ApiModel):
    """One card of `LessonReport.cards` — `score` for a scored card, `unscored` (I4 E31) for an
    ABORTED one; exactly one of the two is non-null."""

    position: int = Field(ge=1)
    session_id: UUID
    weight: float
    score: ScoreReportViewSchema | None
    unscored: UnscoredCardViewSchema | None
    # (I4 E33, HLD 71 §71.10) a scored card's times against its recorded timers and its stored
    # counters; `[]` / `null` for an unscored card.
    norms: list[NormViewSchema]
    failed_rule_count: int | None = Field(ge=0)
    critical_error_count: int | None = Field(ge=0)
    # (I4 E35, HLD 71 §71.12) «Грамотность и адреса» over the same `getSessionReport` view;
    # `null` for an unscored (ABORTED) card, exactly like `score`.
    text_quality: TextQualityReportViewSchema | None
    # (I5 E36, Q-E12-1) Per-leg reaction times; `[]` for an unscored card, like `norms`.
    reaction_times: list[LegReactionTimeViewSchema]
    # (I5 E36, Q-E12-3) The card's participants' logins, joined; «» for an unscored card.
    workstation: str
    # (I5 E38, Q-E9b-3) «Сдал / не сдал» under the card's recorded criteria; `null` for an
    # unscored card, exactly like `score`.
    pass_verdict: PassVerdictViewSchema | None


class LessonReportSchema(ApiModel):
    """`LessonReport`."""

    lesson_id: UUID
    cards: list[LessonReportCardSchema]
    weighted_total: float
    weighted_max: float
    typical_errors: TypicalErrorsSchema
    """(additive, I7 E54, G11) «Типичные ошибки» over this lesson's own sessions; empty rows for
    a trainee's own copy of the report."""


class WeightProposalLineSchema(ApiModel):
    """One card of `WeightProposalSet.proposals`: its current weight beside the proposal."""

    position: int = Field(ge=1)
    scenario_version_id: UUID
    current_weight: float
    proposed_weight: int = Field(ge=MIN_PROPOSED_WEIGHT, le=MAX_PROPOSED_WEIGHT)
    reason_ru: str
    accepted_at: datetime | None


class WeightProposalSetSchema(ApiModel):
    """`WeightProposalSet` (I3 E9a, HLD 70 §70.3.7) — proposals, never applied until accepted."""

    lesson_id: UUID
    source: ProposalSource
    model_name: str | None
    fallback_reason: str | None
    requested_at: datetime
    requested_by_user_id: UUID
    proposals: list[WeightProposalLineSchema]


class WeightProposalAcceptRequestSchema(ApiModel):
    """`WeightProposalAcceptRequest` — the positions whose proposals become weights."""

    positions: list[int] = Field(min_length=1)


class IncidentListItemSchema(ApiModel):
    """`IncidentListItem` — deadlines are session offsets; `null` = not applicable yet."""

    session_id: UUID
    incident_id: UUID
    display_number: int
    lesson_id: UUID | None
    card_status: CardStatus
    session_state: SessionState
    arrived_at_utc: datetime | None
    session_offset_ms: int = Field(ge=0)
    accept_deadline_offset_ms: int | None
    fill_deadline_offset_ms: int | None
    not_completed_deadline_offset_ms: int | None
    classifier_code: str | None
    address_line_ru: str | None
    my_role_type: RoleType | None
    service_leg_status: ServiceResponseStatus | None = None
    """ADDITIVE (I7 E50, memo p.40 «Статус службы»): the viewing ДДС participant's own leg
    status; `null` for a 112-register row, an instructor/admin viewer, or an ambiguous binding."""
    service_leg_status_at_offset_ms: int | None = None
    """ADDITIVE (I7 E50): when `service_leg_status` was last set."""


# -- mappings ------------------------------------------------------------------------------------


def lesson_list_item_schema(listing: StoredLessonListing) -> LessonListItemSchema:
    return LessonListItemSchema(
        lesson_id=UUID(str(listing.lesson_id)),
        title_ru=listing.title_ru,
        session_mode=listing.session_mode,
        state=listing.state,
        card_count=listing.card_count,
        created_at=listing.created_at,
        created_by_user_id=UUID(str(listing.created_by_user_id)),
    )


def lesson_detail_schema(view: LessonDetailView) -> LessonDetailSchema:
    lesson = view.lesson
    return LessonDetailSchema(
        lesson_id=UUID(str(lesson.lesson_id)),
        title_ru=lesson.title_ru,
        session_mode=lesson.session_mode,
        state=lesson.state,
        participants=[
            ParticipantAssignmentSchema(
                user_id=UUID(str(participant.user_id)),
                assigned_role_type=participant.assigned_role_type,
                assigned_service_id=participant.assigned_service_id,
            )
            for participant in lesson.participants
        ],
        scenario_plan=[PlanEntrySchema.of(entry) for entry in lesson.scenario_plan],
        sessions=[
            LessonSessionViewSchema(
                position=card.position,
                session_id=UUID(str(card.session_id)),
                incident_id=UUID(str(card.incident_id)),
                display_number=card.display_number,
                state=card.state,
                card_status=card.card_status,
                arrival=ArrivalSchema.of(card.arrival),
                started_at_lesson_offset_ms=card.started_at_lesson_offset_ms,
                variants=SessionVariantsSchema.of(card.variants),
            )
            for card in view.sessions
        ],
        created_at=lesson.created_at,
        started_at=lesson.started_at,
        completed_at=lesson.completed_at,
        report_released_at=lesson.report_released_at,
        group_id=None if lesson.group_id is None else UUID(str(lesson.group_id)),
        created_by_user_id=UUID(str(lesson.created_by_user_id)),
        shuffle_seed=lesson.shuffle_seed,
    )


def weight_proposal_set_schema(view: WeightProposalsView) -> WeightProposalSetSchema:
    return WeightProposalSetSchema(
        lesson_id=UUID(str(view.lesson_id)),
        source=view.source,
        model_name=view.model_name,
        fallback_reason=view.fallback_reason,
        requested_at=view.requested_at,
        requested_by_user_id=UUID(str(view.requested_by_user_id)),
        proposals=[
            WeightProposalLineSchema(
                position=line.position,
                scenario_version_id=UUID(str(line.scenario_version_id)),
                current_weight=line.current_weight,
                proposed_weight=line.proposed_weight,
                reason_ru=line.reason_ru,
                accepted_at=line.accepted_at,
            )
            for line in view.proposals
        ],
    )


def lesson_report_schema(view: LessonReportView) -> LessonReportSchema:
    cards: list[LessonReportCardSchema] = []
    for card in view.cards:
        report = card.report
        cards.append(
            LessonReportCardSchema(
                position=card.position,
                session_id=UUID(str(card.session_id)),
                weight=card.weight,
                score=(
                    None
                    if report is None
                    else score_report_view_schema(
                        report.score_report,
                        {rule.rule_id: rule for rule in report.scoring_rules},
                        checksum=report.checksum,
                        # (I7 E49, Q-E31-1) The card's own recorded timers, same reading as
                        # `getSessionReport` — a lesson report is a per-card session report.
                        timers=report.timers,
                    )
                ),
                unscored=None if card.unscored is None else unscored_card_schema(card.unscored),
                norms=[] if report is None else [norm_view_schema(n) for n in report.norms],
                failed_rule_count=None if report is None else report.failed_rule_count,
                critical_error_count=None if report is None else report.critical_error_count,
                text_quality=(
                    None if report is None else text_quality_report_schema(report.text_quality)
                ),
                reaction_times=(
                    []
                    if report is None
                    else [leg_reaction_time_schema(r) for r in report.reaction_times]
                ),
                workstation="" if report is None else ", ".join(report.workstations),
                pass_verdict=None if report is None else pass_verdict_schema(report.pass_verdict),
            )
        )
    return LessonReportSchema(
        lesson_id=UUID(str(view.lesson_id)),
        cards=cards,
        weighted_total=view.weighted_total,
        weighted_max=view.weighted_max,
        typical_errors=typical_errors_schema(view.typical_errors),
    )


def unscored_card_schema(view: UnscoredSessionView) -> UnscoredCardViewSchema:
    return UnscoredCardViewSchema(
        state=view.state,
        timeline=[timeline_entry_schema(entry) for entry in view.timeline],
        times=UnscoredCardTimesSchema(
            started_at=view.started_at, aborted_at=view.aborted_at, elapsed_ms=view.elapsed_ms
        ),
    )


def incident_list_item_schema(item: IncidentListItemView) -> IncidentListItemSchema:
    return IncidentListItemSchema(
        session_id=UUID(str(item.session_id)),
        incident_id=UUID(str(item.incident_id)),
        display_number=item.display_number,
        lesson_id=None if item.lesson_id is None else UUID(str(item.lesson_id)),
        card_status=item.card_status,
        session_state=item.session_state,
        arrived_at_utc=item.arrived_at_utc,
        session_offset_ms=item.session_offset_ms,
        accept_deadline_offset_ms=item.accept_deadline_offset_ms,
        fill_deadline_offset_ms=item.fill_deadline_offset_ms,
        not_completed_deadline_offset_ms=item.not_completed_deadline_offset_ms,
        classifier_code=item.classifier_code,
        address_line_ru=item.address_line_ru,
        my_role_type=item.my_role_type,
        service_leg_status=item.service_leg_status,
        service_leg_status_at_offset_ms=item.service_leg_status_at_offset_ms,
    )
