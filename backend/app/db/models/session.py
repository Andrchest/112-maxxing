"""Session aggregate tables (HLD `20-db-schema.md` §20.3).

`simulation_sessions`, `session_participants`, `role_stages`, `incidents`, `world_engine_states`,
and I3's `lessons` (HLD 70 §70.3, §70.8 `0011_lessons`): a lesson owns N ordinary sessions, so its
table sits beside theirs.

`world_engine_states` (additive, E6) is a 1:1 satellite of `incidents`, which is why it lives
here rather than in `layers.py`: it is explicitly **not** a fifth information layer. World truth
holds facts about the world; the engine's bookkeeping — occurrence counters, queued triggers,
how far simulated time has been advanced — is not a fact about anything and D3 forbids merging
the two.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import (
    GEN_RANDOM_UUID,
    JSONB_T,
    NOW,
    TIMESTAMPTZ_T,
    UUID_T,
    Base,
    enum_check,
    metadata_obj,
)
from app.domain.dds.card_status import CardStatus
from app.domain.enums import (
    ClosureReason,
    DDSStageState,
    Operator112StageState,
    RoleType,
    SessionMode,
    SessionState,
)
from app.domain.lesson.lesson import LessonState

#: `incidents.display_number` — the «Происшествие NNNNNNNN» number (HLD 70 §70.3.6, `0011`).
INCIDENT_DISPLAY_NUMBER_SEQ = sa.Sequence("incident_display_number_seq", metadata=metadata_obj)

#: `role_stages.state` carries either an `Operator112StageState` or a `DDSStageState` member; the
#: CHECK lists the union of both enums (HLD §20.3).
ROLE_STAGE_STATES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [member.value for member in Operator112StageState]
        + [member.value for member in DDSStageState]
    )
)


class Lesson(Base):
    """`lessons` — a stream of cards (занятие) as N ordinary sessions (HLD 70 §70.3, D15).

    Scheduling, not simulation: no event log of its own. `participants` and `scenario_plan` are
    jsonb because their shape is the plan's (`LessonParticipant`, `PlanEntry`), read and written
    whole; `variants` is the lesson-wide `VariantsRequest`.
    """

    __tablename__ = "lessons"

    id = sa.Column(UUID_T, primary_key=True)
    title_ru = sa.Column(sa.Text(), nullable=False)
    created_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    session_mode = sa.Column(sa.Text(), nullable=False)
    variants = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    participants = sa.Column(JSONB_T, nullable=False)
    scenario_plan = sa.Column(JSONB_T, nullable=False)
    state = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'CREATED'"))
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    started_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    completed_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    report_released_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    report_released_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    #: I3 E9a (`0013_trainee_groups`): the group the lesson was created for, for the record.
    group_id = sa.Column(
        UUID_T, sa.ForeignKey("trainee_groups.id", ondelete="SET NULL"), nullable=True
    )
    #: I3 E9a: the latest `WeightProposalSet`, never applied until the instructor accepts it.
    weight_proposals = sa.Column(JSONB_T, nullable=True)
    #: I7 E53 (`0020_lesson_shuffle_seed`): «Случайный порядок карточек» — the seed the plan was
    #: permuted with once at creation; `NULL` = the instructor's own order.
    shuffle_seed = sa.Column(sa.BigInteger(), nullable=True)

    __table_args__ = (
        sa.Index("ix_lessons_state", "state"),
        sa.CheckConstraint(enum_check("session_mode", SessionMode), name="session_mode"),
        sa.CheckConstraint(enum_check("state", LessonState), name="state"),
    )


class SimulationSession(Base):
    """`simulation_sessions` — the aggregate root (HLD §20.3, D5, D7)."""

    __tablename__ = "simulation_sessions"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    scenario_version_id = sa.Column(
        UUID_T, sa.ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    session_mode = sa.Column(sa.Text(), nullable=False)
    state = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'CREATED'"))
    session_seed = sa.Column(sa.Text(), nullable=False)
    #: Additive in E5: `openapi.yaml`'s `SessionCreateRequest`/`SessionDetail` both carry
    #: `time_scale` and the domain aggregate holds it, so the session row is its home. `numeric`
    #: (not float) because 0.1 steps must round-trip exactly; the CHECK mirrors the schema's
    #: `minimum: 0.1` / `maximum: 10` (HLD §20.3, "(additive, E5)").
    time_scale = sa.Column(sa.Numeric(4, 2), nullable=False, server_default=sa.text("1"))
    created_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    next_seq_no = sa.Column(sa.BigInteger(), nullable=False, server_default=sa.text("1"))
    started_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    paused_total_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    #: Additive in E17 (ruling R1, HLD §20.3): the session offset a currently open
    #: `ROLE_TRANSITION` began at, `NULL` outside one. Simulated time is frozen at it while
    #: the hand-over lasts, and `finish_role_transition` — the one writer of
    #: `paused_total_ms` — banks the interval's length there and clears this column.
    role_transition_started_offset_ms = sa.Column(sa.Integer(), nullable=True)
    completed_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    abort_reason = sa.Column(sa.Text(), nullable=True)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    #: Additive in E16 (HLD §20.3, D6, D11): *whether an instructor has actually released this
    #: session's report to its trainees*. Distinct from
    #: `SessionPolicy.report_visible_to_trainee_before_release`, which is a static per-mode
    #: constant saying whether a release is needed at all (`10-domain-model.md` §10.10). Both
    #: columns are NULL until the release happens and move together (the CHECK below).
    report_released_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    report_released_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    #: Additive in I3 E1 (HLD 70 §70.2.2, migration `0009_session_variants`): the resolved
    #: `SessionVariants`, a materialised copy of `SESSION_CREATED.variants` like `time_scale`.
    #: `'{}'` (every session created before E1) reads as the schema-1 derivation of the
    #: session's own stage chain (`app.domain.session.variants.legacy_session_variants`).
    variants = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    #: Additive in I3 E4a (HLD 70 §70.3.2, `0011_lessons`): the lesson this session is a card
    #: of and its plan position — both or neither (a single session has neither).
    lesson_id = sa.Column(UUID_T, sa.ForeignKey("lessons.id", ondelete="RESTRICT"), nullable=True)
    lesson_position = sa.Column(sa.Integer(), nullable=True)

    __table_args__ = (
        sa.Index("ix_sessions_state", "state"),
        sa.UniqueConstraint("lesson_id", "lesson_position", name="uq_sessions_lesson_position"),
        sa.CheckConstraint(
            "(lesson_id IS NULL) = (lesson_position IS NULL)", name="lesson_position_together"
        ),
        sa.Index("ix_sessions_scenario_version", "scenario_version_id"),
        sa.CheckConstraint(enum_check("session_mode", SessionMode), name="session_mode"),
        sa.CheckConstraint(enum_check("state", SessionState), name="state"),
        sa.CheckConstraint("time_scale >= 0.1 AND time_scale <= 10", name="time_scale"),
        sa.CheckConstraint(
            "(report_released_at IS NULL) = (report_released_by_user_id IS NULL)",
            name="report_released_together",
        ),
        sa.CheckConstraint(
            "role_transition_started_offset_ms IS NULL OR role_transition_started_offset_ms >= 0",
            name="role_transition_offset_non_negative",
        ),
    )


class SessionParticipant(Base):
    """`session_participants` (HLD §20.3)."""

    __tablename__ = "session_participants"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assigned_role_type = sa.Column(sa.Text(), nullable=True)
    joined_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    # `0012_dds_response_status` (I3 E5a, HLD 70 §70.4.5, §70.8): ДДС participant → service
    # binding; distinct per session. Written by E5b; E5a lands the column.
    assigned_service_id = sa.Column(sa.Text(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("session_id", "user_id", name="uq_participants_session_user"),
        sa.CheckConstraint(
            enum_check("assigned_role_type", RoleType, nullable=True), name="assigned_role_type"
        ),
        sa.CheckConstraint(
            "assigned_service_id IS NULL OR assigned_service_id <> ''",
            name="assigned_service_id",
        ),
        sa.Index(
            "uq_participants_session_service",
            "session_id",
            "assigned_service_id",
            unique=True,
            postgresql_where=sa.text("assigned_service_id IS NOT NULL"),
        ),
    )


class RoleStage(Base):
    """`role_stages` — materialized from the event log (HLD §20.3)."""

    __tablename__ = "role_stages"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    role_type = sa.Column(sa.Text(), nullable=False)
    order_index = sa.Column(sa.Integer(), nullable=False)
    state = sa.Column(sa.Text(), nullable=False)
    participant_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    started_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    completed_at_offset_ms = sa.Column(sa.Integer(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("session_id", "order_index", name="uq_role_stages_session_order"),
        sa.Index("ix_role_stages_session_state", "session_id", "state"),
        sa.CheckConstraint(enum_check("role_type", RoleType), name="role_type"),
        sa.CheckConstraint(enum_check("state", ROLE_STAGE_STATES), name="state"),
    )


class Incident(Base):
    """`incidents` — one session, one incident (HLD §20.3, SPEC §13)."""

    __tablename__ = "incidents"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    scenario_version_id = sa.Column(
        UUID_T, sa.ForeignKey("scenario_versions.id", ondelete="RESTRICT"), nullable=False
    )
    created_at_offset_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    closed_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    closure_reason = sa.Column(sa.Text(), nullable=True)
    #: Additive in I3 E4a (HLD 70 §70.4.6, `0011_lessons`): the derived card status, materialised
    #: in the Unit of Work of the event that changed it (`CHECKED`: by the report release).
    card_status = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'REGISTERED'"))
    #: The «Происшествие NNNNNNNN» number, from `incident_display_number_seq`.
    display_number = sa.Column(
        sa.BigInteger(),
        INCIDENT_DISPLAY_NUMBER_SEQ,
        nullable=False,
        server_default=INCIDENT_DISPLAY_NUMBER_SEQ.next_value(),
    )

    __table_args__ = (
        sa.UniqueConstraint("session_id", name="uq_incidents_session"),
        sa.UniqueConstraint("display_number", name="uq_incidents_display_number"),
        sa.CheckConstraint(
            enum_check("closure_reason", ClosureReason, nullable=True), name="closure_reason"
        ),
        sa.CheckConstraint(enum_check("card_status", CardStatus), name="card_status"),
    )


class WorldEngineState(Base):
    """`world_engine_states` — the world event engine's bookkeeping (additive, E6; D3, D7).

    One row per incident, written only by `tick_session` and created zeroed by session creation.
    `bookkeeping` is a single jsonb document (`occurrences`, `last_fired_ms`, `scheduled`,
    `emotion_applications`, `reached_states`) because its shape is scenario-defined — the keys are
    `world_event_id`s and emotion rule ids — exactly the reason §20.4 gives for its own jsonb
    columns. `EventIndex` is absent on purpose: it is re-folded from `session_events` on load, so
    the event log stays the single source of what happened (D5).
    """

    __tablename__ = "world_engine_states"

    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    last_tick_ms = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    last_folded_seq_no = sa.Column(sa.BigInteger(), nullable=False, server_default=sa.text("0"))
    bookkeeping = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    updated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
