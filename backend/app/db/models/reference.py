"""Reference data tables (HLD `20-db-schema.md` §20.2).

`users`, `scenarios`, `scenario_versions`, `scoring_rules`, and I3 E9a's `trainee_groups` /
`trainee_group_members` (HLD 70 §70.3.7, `0013_trainee_groups`) — account-side lists, beside
`users`.
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
from app.domain.enums import EvaluatorType, ScoringCategory

# `users.role` has no counterpart in `app.domain.enums` (D8 names the three values in prose only),
# so the members are spelled here exactly as `20-db-schema.md` §20.2 gives them.
USER_ROLES: tuple[str, ...] = ("TRAINEE", "INSTRUCTOR", "ADMIN")


class User(Base):
    """`users` — accounts (HLD §20.2, D8)."""

    __tablename__ = "users"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    username = sa.Column(sa.Text(), nullable=False)
    password_hash = sa.Column(sa.Text(), nullable=False)
    display_name_ru = sa.Column(sa.Text(), nullable=False)
    role = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'TRAINEE'"))
    is_active = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("true"))
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    #: I3 E6e (HLD 80 §80.7, migration `0015_users_sip_ha1`): the optional per-user SIP Digest
    #: HA1, `MD5(username:realm:password)`; `NULL` ⇒ the deployment SIP password applies.
    sip_ha1 = sa.Column(sa.Text(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint(enum_check("role", USER_ROLES), name="role"),
        sa.CheckConstraint("sip_ha1 IS NULL OR sip_ha1 ~ '^[0-9a-f]{32}$'", name="sip_ha1_hex"),
    )


class TraineeGroup(Base):
    """`trainee_groups` — a named list of trainees an instructor builds lessons for (I3 E9a)."""

    __tablename__ = "trainee_groups"

    id = sa.Column(UUID_T, primary_key=True)
    name_ru = sa.Column(sa.Text(), nullable=False)
    created_by_user_id = sa.Column(
        UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (sa.CheckConstraint("name_ru <> ''", name="name_ru_not_empty"),)


class TraineeGroupMember(Base):
    """`trainee_group_members` — one row per (group, trainee) (I3 E9a)."""

    __tablename__ = "trainee_group_members"

    group_id = sa.Column(
        UUID_T, sa.ForeignKey("trainee_groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)

    __table_args__ = (sa.Index("ix_trainee_group_members_user", "user_id"),)


class Scenario(Base):
    """`scenarios` — scenario identity (HLD §20.2, D4)."""

    __tablename__ = "scenarios"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    slug = sa.Column(sa.Text(), nullable=False)
    title_ru = sa.Column(sa.Text(), nullable=False)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (sa.UniqueConstraint("slug", name="uq_scenarios_slug"),)


class ScenarioVersion(Base):
    """`scenario_versions` — versioned scenario content, immutable once locked (HLD §20.2, D4)."""

    __tablename__ = "scenario_versions"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    scenario_id = sa.Column(
        UUID_T, sa.ForeignKey("scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    version = sa.Column(sa.Integer(), nullable=False)
    schema_version = sa.Column(sa.Integer(), nullable=False)
    title = sa.Column(sa.Text(), nullable=False)
    description = sa.Column(sa.Text(), nullable=False, server_default=sa.text("''"))
    difficulty = sa.Column(sa.SmallInteger(), nullable=False, server_default=sa.text("1"))
    deterministic_seed = sa.Column(sa.Text(), nullable=False)
    role_chain = sa.Column(TEXT_ARRAY_T, nullable=False)
    content = sa.Column(JSONB_T, nullable=False)
    content_sha256 = sa.Column(sa.Text(), nullable=False)
    source_path = sa.Column(sa.Text(), nullable=True)
    locked_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.UniqueConstraint("scenario_id", "version", name="uq_scenario_versions_scenario_version"),
        sa.Index("ix_scenario_versions_scenario", "scenario_id"),
        sa.CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty"),
    )


class ScoringRule(Base):
    """`scoring_rules` — projection of `scenario_versions.content.scoring_rules` (HLD §20.2)."""

    __tablename__ = "scoring_rules"

    scenario_version_id = sa.Column(
        UUID_T, sa.ForeignKey("scenario_versions.id", ondelete="CASCADE"), primary_key=True
    )
    rule_id = sa.Column(sa.Text(), primary_key=True)
    name_ru = sa.Column(sa.Text(), nullable=False)
    description_ru = sa.Column(sa.Text(), nullable=False, server_default=sa.text("''"))
    category = sa.Column(sa.Text(), nullable=False)
    max_points = sa.Column(sa.Numeric(8, 2), nullable=False)
    critical = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    evaluator_type = sa.Column(sa.Text(), nullable=False)
    config = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    min_evidence = sa.Column(sa.SmallInteger(), nullable=False, server_default=sa.text("1"))
    order_index = sa.Column(sa.Integer(), nullable=False)
    applies_to_roles = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'[]'::jsonb"))
    """The `RoleType` values this rule scores; `[]` (the default) means it always applies (R7,
    `10-domain-model.md` §10.14 "Applicability", migration `0005_scoring_applies_to_roles`)."""
    applies_to_variants = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    """Switch → the variant values this rule scores; `{}` (the default) means it always applies
    (HLD 70 §70.2.5, D14, migration `0009_session_variants`)."""

    __table_args__ = (
        sa.CheckConstraint("max_points > 0", name="max_points"),
        sa.CheckConstraint("min_evidence >= 1", name="min_evidence"),
        sa.CheckConstraint(enum_check("category", ScoringCategory), name="category"),
        sa.CheckConstraint(enum_check("evaluator_type", EvaluatorType), name="evaluator_type"),
    )
