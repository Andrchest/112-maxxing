"""The four information layers (HLD `20-db-schema.md` §20.4, D3).

`incident_world_states`, `incident_caller_beliefs`, `incident_cards`,
`incident_card_revisions`, `handoff_snapshots`.

Four layers, four storage locations: no table here joins WorldTruth to the card, and the DDS side
reaches trainee data only through `handoff_snapshots` (D3, SPEC §10).
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import (
    GEN_RANDOM_UUID,
    JSONB_T,
    NOW,
    TEXT_ARRAY_T,
    TIMESTAMPTZ_T,
    UUID_T,
    Base,
    enum_check,
)
from app.domain.enums import ActorType

#: SPEC §9 / §42 test 4: neither `MODEL` nor `SIMULATION` may write a card revision, and the
#: database is where that is enforced.
CARD_REVISION_ACTOR_TYPES: tuple[ActorType, ...] = (ActorType.TRAINEE, ActorType.INSTRUCTOR)


class IncidentWorldState(Base):
    """`incident_world_states` — WorldTruth, engine-written only (HLD §20.4, D3)."""

    __tablename__ = "incident_world_states"

    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    revision = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    facts = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    value_types = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    updated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)


class IncidentCallerBelief(Base):
    """`incident_caller_beliefs` — CallerBelief, engine-written only (HLD §20.4, D3)."""

    __tablename__ = "incident_caller_beliefs"

    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    revision = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    facts = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    knowledge = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    certainty = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    emotion = sa.Column(JSONB_T, nullable=False)
    revealed_fact_ids = sa.Column(TEXT_ARRAY_T, nullable=False, server_default=sa.text("'{}'"))
    updated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)


class IncidentCard(Base):
    """`incident_cards` — materialized view of `incident_card_revisions` (HLD §20.4)."""

    __tablename__ = "incident_cards"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    values = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    revision_counter = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    updated_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (sa.UniqueConstraint("incident_id", name="uq_incident_cards_incident"),)


class IncidentCardRevision(Base):
    """`incident_card_revisions` — the append-only card audit record (HLD §20.4, SPEC §9)."""

    __tablename__ = "incident_card_revisions"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    card_id = sa.Column(
        UUID_T, sa.ForeignKey("incident_cards.id", ondelete="CASCADE"), nullable=False
    )
    revision_no = sa.Column(sa.Integer(), nullable=False)
    field_path = sa.Column(sa.Text(), nullable=False)
    previous_value = sa.Column(JSONB_T, nullable=True)
    new_value = sa.Column(JSONB_T, nullable=True)
    value_type = sa.Column(sa.Text(), nullable=False)
    actor_type = sa.Column(sa.Text(), nullable=False)
    actor_user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    at_offset_ms = sa.Column(sa.Integer(), nullable=False)
    session_event_id = sa.Column(
        UUID_T, sa.ForeignKey("session_events.id", ondelete="RESTRICT"), nullable=True
    )
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.UniqueConstraint("card_id", "revision_no", name="uq_card_revisions_card_no"),
        sa.Index("ix_card_revisions_card_path", "card_id", "field_path", "revision_no"),
        sa.CheckConstraint(enum_check("actor_type", CARD_REVISION_ACTOR_TYPES), name="actor_type"),
    )


class HandoffSnapshot(Base):
    """`handoff_snapshots` — the immutable by-value copy handed to DDS (HLD §20.4, SPEC §10)."""

    __tablename__ = "handoff_snapshots"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    incident_id = sa.Column(
        UUID_T, sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    card_id = sa.Column(
        UUID_T, sa.ForeignKey("incident_cards.id", ondelete="RESTRICT"), nullable=False
    )
    card_revision_id = sa.Column(
        UUID_T, sa.ForeignKey("incident_card_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    card_values = sa.Column(JSONB_T, nullable=False)
    recipient_services = sa.Column(TEXT_ARRAY_T, nullable=False)
    content_sha256 = sa.Column(sa.Text(), nullable=False)
    created_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at_offset_ms = sa.Column(sa.Integer(), nullable=False)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.Index("ix_handoff_snapshots_incident", "incident_id", "created_at_offset_ms"),
    )
