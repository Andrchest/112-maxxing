"""DDS, resources and notifications (HLD `20-db-schema.md` §20.5).

`dds_assignments`, `emergency_resources`, `resource_state_changes`, `notifications`.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import GEN_RANDOM_UUID, JSONB_T, TEXT_ARRAY_T, UUID_T, Base, enum_check
from app.domain.enums import (
    DDSStageState,
    NotificationSeverity,
    ResourceStatus,
    RoleType,
    ServiceType,
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

    __table_args__ = (
        sa.UniqueConstraint(
            "role_stage_id", "service_type", name="uq_dds_assignments_stage_service"
        ),
        sa.Index("ix_dds_assignments_incident", "incident_id"),
        sa.CheckConstraint(enum_check("service_type", ServiceType), name="service_type"),
        sa.CheckConstraint(enum_check("state", DDSStageState), name="state"),
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
