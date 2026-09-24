"""DDS, resources and notifications (HLD `20-db-schema.md` §20.5).

`dds_assignments`, `emergency_resources`, `resource_state_changes`, `notifications`, and — I3 E5a —
`dds_service_status_history`.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, JSONB_T, TEXT_ARRAY_T, UUID_T, Base, enum_check
from app.domain.dds.response import LegResponder, ServiceResponseStatus
from app.domain.enums import (
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
)


class DDSAssignment(Base):
    """`dds_assignments` — materialized from the event log (HLD §20.5, SPEC §10)."""

    __tablename__ = "dds_assignments"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    role_stage_id = sa.Column(
        UUID_T, sa.ForeignKey("role_stages.id", ondelete="CASCADE"), nullable=False
    )
    # No FK to `incident_cards`: the DDS side reaches trainee data only through the snapshot (D3).
    snapshot_id = sa.Column(
        UUID_T, sa.ForeignKey("handoff_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    service_type = sa.Column(sa.Text(), nullable=False)
    state = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'RECEIVED'"))
    received_at_offset_ms = sa.Column(sa.Integer(), nullable=False)
    acknowledged_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    dispatched_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    closed_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    closure_reason = sa.Column(sa.Text(), nullable=True)
    # `0012_dds_response_status` (I3 E5a, HLD 70 §70.4.3, §70.8): the memo's per-leg status.
    response_status = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'ADDED'"))
    response_status_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    order_number = sa.Column(sa.Text(), nullable=True)
    last_comment_ru = sa.Column(sa.Text(), nullable=True)
    accept_missed = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    responder = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'TRAINEE'"))
    bound_user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint(
            "role_stage_id", "service_type", name="uq_dds_assignments_stage_service"
        ),
        sa.Index("ix_dds_assignments_incident", "incident_id"),
        # `0010_service_id_open` (I3 E2a, HLD 70 §70.8, D18): a service is a catalog id, no longer
        # one of six enum members, so the CHECK only refuses the empty string.
        sa.CheckConstraint("service_type <> ''", name="service_type"),
        sa.CheckConstraint(enum_check("state", DDSStageState), name="state"),
        sa.CheckConstraint(
            enum_check("response_status", ServiceResponseStatus), name="response_status"
        ),
        sa.CheckConstraint(enum_check("responder", LegResponder), name="responder"),
    )


class DDSServiceStatusHistory(Base):
    """`dds_service_status_history` — append-only, one row per `DDS_SERVICE_STATUS_SET`
    (I3 E5a, HLD 70 §70.4.3, §70.8). UPDATE/DELETE are rejected by trigger (§20.9 pattern)."""

    __tablename__ = "dds_service_status_history"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id = sa.Column(
        UUID_T, sa.ForeignKey("dds_assignments.id", ondelete="CASCADE"), nullable=False
    )
    event_id = sa.Column(
        UUID_T, sa.ForeignKey("session_events.id", ondelete="RESTRICT"), nullable=False
    )
    seq_no = sa.Column(sa.BigInteger(), nullable=False)
    previous_status = sa.Column(sa.Text(), nullable=False)
    new_status = sa.Column(sa.Text(), nullable=False)
    order_number = sa.Column(sa.Text(), nullable=True)
    comment_ru = sa.Column(sa.Text(), nullable=True)
    completion_reason = sa.Column(sa.Text(), nullable=True)
    source = sa.Column(sa.Text(), nullable=False)
    actor_type = sa.Column(sa.Text(), nullable=False)
    actor_user_id = sa.Column(UUID_T, nullable=True)
    at_offset_ms = sa.Column(sa.Integer(), nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("event_id", name="uq_dds_service_status_history_event"),
        sa.Index("ix_dds_service_status_history_assignment", "assignment_id", "seq_no"),
    )


class EmergencyResource(Base):
    """`emergency_resources` — per-session resource instances (HLD §20.5, SPEC §11)."""

    __tablename__ = "emergency_resources"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    scenario_resource_id = sa.Column(sa.Text(), nullable=False)
    service_type = sa.Column(sa.Text(), nullable=False)
    resource_type = sa.Column(sa.Text(), nullable=False)
    callsign = sa.Column(sa.Text(), nullable=False)
    name_ru = sa.Column(sa.Text(), nullable=False)
    capabilities = sa.Column(TEXT_ARRAY_T, nullable=False, server_default=sa.text("'{}'"))
    current_status = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'AVAILABLE'"))
    home_station_ru = sa.Column(sa.Text(), nullable=False, server_default=sa.text("''"))
    crew_size = sa.Column(sa.SmallInteger(), nullable=False, server_default=sa.text("1"))
    availability = sa.Column(JSONB_T, nullable=False)
    eta = sa.Column(JSONB_T, nullable=False)
    status_changed_at_offset_ms = sa.Column(
        sa.Integer(), nullable=False, server_default=sa.text("0")
    )
    assignment_id = sa.Column(
        UUID_T, sa.ForeignKey("dds_assignments.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "session_id", "scenario_resource_id", name="uq_resources_session_scenario_id"
        ),
        sa.UniqueConstraint("session_id", "callsign", name="uq_resources_session_callsign"),
        sa.Index(
            "ix_resources_session_service_status", "session_id", "service_type", "current_status"
        ),
        sa.Index("ix_resources_capabilities", "capabilities", postgresql_using="gin"),
        sa.CheckConstraint(enum_check("current_status", ResourceStatus), name="current_status"),
    )


class ResourceStateChange(Base):
    """`resource_state_changes` — append-only resource audit (HLD §20.5, SPEC §29)."""

    __tablename__ = "resource_state_changes"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    resource_id = sa.Column(
        UUID_T, sa.ForeignKey("emergency_resources.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id = sa.Column(
        UUID_T, sa.ForeignKey("dds_assignments.id", ondelete="SET NULL"), nullable=True
    )
    previous_status = sa.Column(sa.Text(), nullable=True)
    new_status = sa.Column(sa.Text(), nullable=False)
    trigger = sa.Column(sa.Text(), nullable=False)
    source_world_event_id = sa.Column(sa.Text(), nullable=True)
    at_offset_ms = sa.Column(sa.Integer(), nullable=False)
    session_event_id = sa.Column(
        UUID_T, sa.ForeignKey("session_events.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        sa.Index("ix_resource_state_changes_resource", "resource_id", "at_offset_ms"),
    )


class Notification(Base):
    """`notifications` — materialized from the event log (HLD §20.5, additive per D5)."""

    __tablename__ = "notifications"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    audience_role = sa.Column(sa.Text(), nullable=False)
    severity = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'INFO'"))
    title_ru = sa.Column(sa.Text(), nullable=False)
    body_ru = sa.Column(sa.Text(), nullable=False, server_default=sa.text("''"))
    source_world_event_id = sa.Column(sa.Text(), nullable=True)
    created_at_offset_ms = sa.Column(sa.Integer(), nullable=False)
    acknowledged_at_offset_ms = sa.Column(sa.Integer(), nullable=True)
    acknowledged_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        sa.Index(
            "ix_notifications_incident_role",
            "incident_id",
            "audience_role",
            "created_at_offset_ms",
        ),
        sa.CheckConstraint(enum_check("audience_role", RoleType), name="audience_role"),
        sa.CheckConstraint(enum_check("severity", NotificationSeverity), name="severity"),
    )
