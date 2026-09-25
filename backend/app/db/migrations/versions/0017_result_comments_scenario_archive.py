"""result_comments + scenarios.archived_at (I4 E32, HLD `71-i4-wave4.md` §71.9, HLD 20 §20.11.2,
§20.11.3).

Additive only (P1): one new append-only table and one nullable column,

* `result_comments` — instructor feedback on a session or a lesson result (ТЗ ¶236, ¶237), append-
  only: an edit is a new row pointing at the one it replaces (`replaces_comment_id`), never an
  `UPDATE`. Exactly one of `session_id` / `lesson_id` is set (`CHECK`). Guarded by the §20.9 shared
  `trg_reject_mutation()`, the same trigger `0016_audit_log` uses;
* `scenarios.archived_at` — `NULL` = active; set by `archiveScenario`, cleared by
  `unarchiveScenario` (ТЗ ¶229, "удалять неактуальные сценарии" = archive, because
  `scenario_versions`/sessions keep their `RESTRICT` FK to `scenarios`, so no scenario row is ever
  deleted).

No backfill: both start with nothing archived and no comments.

**Technical note (E32's own, the design is silent on it): `alembic_version.version_num` is widened
first.** This revision's own id, `0017_result_comments_scenario_archive`, is 37 characters —
past Alembic's default `alembic_version.version_num VARCHAR(32)`, created by the very first
migration in this project's history. Every revision id before this one happened to fit; this one
does not, and `E24`'s wave-4 plan pre-allocates the literal name (`71-i4-wave4.md` §71.1), so it is
not this migration's place to shorten it. Widening the column to `VARCHAR(255)` here, before
anything else, is the minimal fix: it is forward-only (a later `ALTER … TYPE` never re-narrows,
since a shorter column could truncate a revision id a later migration might legitimately need) and
touches no other table.

Revision ID: 0017_result_comments_scenario_archive
Revises: 0016_audit_log
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import GEN_RANDOM_UUID, NOW, TIMESTAMPTZ_T, UUID_T

revision: str = "0017_result_comments_scenario_archive"
down_revision: str | None = "0016_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "result_comments"
_TRIGGER = "result_comments_append_only"


def upgrade() -> None:
    # See the module docstring: this revision id is 37 characters, past Alembic's default
    # `VARCHAR(32)` for `alembic_version.version_num`. Widen it first so the version bump at the
    # end of this migration (and any longer id a later migration might need) can be written.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
    )
    op.create_table(
        _TABLE,
        sa.Column("id", UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID),
        sa.Column(
            "session_id",
            UUID_T,
            sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "lesson_id", UUID_T, sa.ForeignKey("lessons.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "author_user_id", UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "replaces_comment_id",
            UUID_T,
            sa.ForeignKey("result_comments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", TIMESTAMPTZ_T, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "(session_id IS NULL) <> (lesson_id IS NULL)", name="exactly_one_target"
        ),
        sa.CheckConstraint("length(text) > 0", name="text_not_empty"),
    )
    op.create_index(
        "ix_result_comments_session",
        _TABLE,
        ["session_id", "created_at"],
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_result_comments_lesson",
        _TABLE,
        ["lesson_id", "created_at"],
        postgresql_where=sa.text("lesson_id IS NOT NULL"),
    )
    op.execute(
        f"CREATE TRIGGER {_TRIGGER} BEFORE UPDATE OR DELETE ON {_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION trg_reject_mutation()"
    )
    op.add_column("scenarios", sa.Column("archived_at", TIMESTAMPTZ_T, nullable=True))


def downgrade() -> None:
    op.drop_column("scenarios", "archived_at")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}")
    op.drop_index("ix_result_comments_lesson", table_name=_TABLE)
    op.drop_index("ix_result_comments_session", table_name=_TABLE)
    op.drop_table(_TABLE)
