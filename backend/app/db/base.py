"""Declarative base, naming convention and column-type helpers (HLD `20-db-schema.md`).

`docs/hld/20-db-schema.md` is the single owner of every table, column, index, constraint and
trigger definition; this module only provides the shared machinery the model modules use so that
all 25 tables spell those definitions the same way.

ORM classes are a separate set of classes from the domain types of `docs/hld/10-domain-model.md`:
they never inherit from, embed or wrap a domain object (D2, D3). The only thing this layer takes
from the domain is the *enum membership* of the `TEXT + CHECK` columns, imported from
`app.domain.enums` / `app.domain.events.types` so the database CHECK and the Python enum cannot
drift apart (HLD §20 conventions).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import DeclarativeBase

# Explicit names are given for every index and UNIQUE constraint because `20-db-schema.md` names
# them literally (`ix_sessions_state`, `uq_users_username`, ...) and those names are not derivable
# from the column list. The convention below therefore only has to cover primary keys, foreign
# keys and check constraints, whose names the HLD leaves to us.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = sa.MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every ORM model in `app.db.models`."""

    metadata = metadata_obj


# --------------------------------------------------------------------------------------------
# Column type helpers (HLD §20 "Conventions used throughout")
# --------------------------------------------------------------------------------------------

#: `uuid` — primary keys and foreign keys.
UUID_T = pg.UUID(as_uuid=True)
#: `jsonb` — versioned/configurable payload portions only (SPEC §30).
JSONB_T = pg.JSONB(astext_type=sa.Text())
#: `timestamptz` — every timestamp column.
TIMESTAMPTZ_T = sa.TIMESTAMP(timezone=True)
#: `text[]` — real PostgreSQL arrays (`role_chain`, `capabilities`, ...).
TEXT_ARRAY_T = pg.ARRAY(sa.Text())

#: `DEFAULT gen_random_uuid()` (extension `pgcrypto`).
GEN_RANDOM_UUID = sa.text("gen_random_uuid()")
#: `DEFAULT now()`.
NOW = sa.text("now()")


def pk_uuid_column() -> sa.Column[Any]:
    """The standard `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` column."""
    return sa.Column("id", UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)


def sql_in_list(values: Iterable[object]) -> str:
    """Render `values` as a SQL `IN (...)` member list: `'A','B','C'`.

    Members come from the domain enums, so the CHECK constraint in the database and the Python
    enum are generated from one source and cannot drift (HLD §20).
    """
    rendered = [str(getattr(value, "value", value)) for value in values]
    for item in rendered:
        if "'" in item:  # pragma: no cover - domain enum values are bare ASCII identifiers
            raise ValueError(f"enum value {item!r} cannot be inlined into a CHECK constraint")
    return ", ".join(f"'{item}'" for item in rendered)


def enum_check(column: str, values: Iterable[object], *, nullable: bool = False) -> str:
    """Return the SQL text of a `CHECK (col IN (...))` constraint for an enum-like TEXT column."""
    members = sql_in_list(values)
    if nullable:
        return f"{column} IS NULL OR {column} IN ({members})"
    return f"{column} IN ({members})"
