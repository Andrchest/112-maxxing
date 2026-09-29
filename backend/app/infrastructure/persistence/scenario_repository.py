"""`SqlAlchemyScenarioRepository` — `scenarios`, `scenario_versions`, `scoring_rules` (§20.2, D4).

`lock_scenario_version` is the SPEC §42 invariant 6 hinge: it sets `locked_at` if and only if it is
still null, which arms the `scenario_versions_locked_guard` trigger of §20.2 so that every later
UPDATE of `content` / `content_sha256` — through the ORM or through raw SQL — is rejected by
PostgreSQL itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.scenario_repository import (
    StoredScenario,
    StoredScenarioListing,
    StoredScenarioVersion,
    StoredScenarioVersionDetail,
)
from app.db.models.reference import Scenario as ScenarioRow
from app.db.models.reference import ScenarioVersion as ScenarioVersionRow
from app.db.models.reference import ScoringRule as ScoringRuleRow
from app.domain.common.ids import ScenarioId, ScenarioVersionId
from app.domain.enums import RoleType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.rules import ScoringRule
from app.domain.session.variants import ScenarioVariants, derive_scenario_variants
from app.infrastructure.persistence.mappers import (
    scenario_version_row_values,
    scoring_rule_row_values,
)

__all__ = ["SqlAlchemyScenarioRepository"]

_SCENARIOS = ScenarioRow.__table__
_VERSIONS = ScenarioVersionRow.__table__
_RULES = ScoringRuleRow.__table__


# --- I7 E53 (G13): the latest version's incident facts, for the scenario's category -----------


def _latest_content_value(expression: Any, label: str) -> Any:
    """One value of the latest version's `content`, as a correlated scalar subquery."""
    latest = _VERSIONS.alias("latest_facts")
    return (
        sa.select(expression(latest.c.content))
        .where(latest.c.scenario_id == _SCENARIOS.c.id)
        .order_by(latest.c.version.desc())
        .limit(1)
        .scalar_subquery()
        .label(label)
    )


def _category_fact_columns() -> tuple[Any, Any, Any]:
    """`latest_reference_pack`, `latest_classifier_code`, `latest_incident_types` (jsonb)."""

    def card_values(content: Any) -> Any:
        return content["expected_response"]["prefab_handoff"]["card_values"]

    return (
        _latest_content_value(
            lambda content: content["reference_pack"].astext, "latest_reference_pack"
        ),
        _latest_content_value(
            lambda content: sa.func.coalesce(
                card_values(content)["incident.classifier_code"].astext,
                content["world_truth"]["facts"]["incident.classifier_code"]["world_value"].astext,
            ),
            "latest_classifier_code",
        ),
        _latest_content_value(
            lambda content: card_values(content)["incident.types"], "latest_incident_types"
        ),
    )


def _category_facts(row: Any) -> dict[str, Any]:
    """The three raw values of a row selected with `_category_fact_columns`."""
    types = row.latest_incident_types
    if isinstance(types, str):
        types = json.loads(types)
    return {
        "latest_reference_pack": row.latest_reference_pack,
        "latest_classifier_code": row.latest_classifier_code,
        "latest_incident_types": (
            tuple(str(code) for code in types) if isinstance(types, list) else ()
        ),
    }


# --- end I7 E53 --------------------------------------------------------------------------------


class SqlAlchemyScenarioRepository:
    """`ScenarioRepository` over PostgreSQL, bound to one `AsyncSession` (one transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_scenario_by_slug(self, slug: str) -> StoredScenario | None:
        result = await self._session.execute(
            sa.select(
                _SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru, _SCENARIOS.c.archived_at
            ).where(_SCENARIOS.c.slug == slug)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenario(
            scenario_id=ScenarioId(UUID(str(row.id))),
            slug=row.slug,
            title_ru=row.title_ru,
            archived_at=row.archived_at,
        )

    async def get_scenario(self, scenario_id: ScenarioId) -> StoredScenario | None:
        result = await self._session.execute(
            sa.select(
                _SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru, _SCENARIOS.c.archived_at
            ).where(_SCENARIOS.c.id == UUID(str(scenario_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenario(
            scenario_id=ScenarioId(UUID(str(row.id))),
            slug=row.slug,
            title_ru=row.title_ru,
            archived_at=row.archived_at,
        )

    async def get_version(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersion | None:
        result = await self._session.execute(
            sa.select(
                _VERSIONS.c.id,
                _VERSIONS.c.scenario_id,
                _VERSIONS.c.version,
                _VERSIONS.c.content_sha256,
                _VERSIONS.c.locked_at,
            ).where(_VERSIONS.c.id == UUID(str(scenario_version_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenarioVersion(
            scenario_version_id=ScenarioVersionId(UUID(str(row.id))),
            scenario_id=ScenarioId(UUID(str(row.scenario_id))),
            version=int(row.version),
            content_sha256=row.content_sha256,
            locked_at=row.locked_at,
        )

    async def get_version_document(
        self, scenario_version_id: ScenarioVersionId
    ) -> Mapping[str, Any] | None:
        """The stored `content` of a version — the full validated document (§20.2)."""
        result = await self._session.execute(
            sa.select(_VERSIONS.c.content).where(_VERSIONS.c.id == UUID(str(scenario_version_id)))
        )
        row = result.one_or_none()
        if row is None:
            return None
        return dict(row.content)

    # -- read paths for `listScenarios` / `listScenarioVersions` (E7) --------------------------

    async def list_scenarios(
        self, *, limit: int, offset: int, include_archived: bool = False
    ) -> tuple[list[StoredScenarioListing], int]:
        """One page of scenarios with their version aggregates, plus the unpaged total.

        `version_count` and `latest_version` come from a `LEFT JOIN … GROUP BY`, so a scenario
        with no versions yet still appears — with `0` and `null`, which is what
        `ScenarioSummary.latest_version` being nullable means.

        `include_archived=False` (I4 E32, the default) excludes every row with `archived_at IS
        NOT NULL` from both the page and the total.
        """
        archived_filter = () if include_archived else (_SCENARIOS.c.archived_at.is_(None),)

        total_result = await self._session.execute(
            sa.select(sa.func.count()).select_from(_SCENARIOS).where(*archived_filter)
        )
        total = int(total_result.scalar_one())

        # I3 E9a: the latest version's difficulty, one correlated read per listed scenario.
        latest = _VERSIONS.alias("latest")
        latest_difficulty = (
            sa.select(latest.c.difficulty)
            .where(latest.c.scenario_id == _SCENARIOS.c.id)
            .order_by(latest.c.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        result = await self._session.execute(
            sa.select(
                _SCENARIOS.c.id,
                _SCENARIOS.c.slug,
                _SCENARIOS.c.title_ru,
                _SCENARIOS.c.archived_at,
                sa.func.count(_VERSIONS.c.id).label("version_count"),
                sa.func.max(_VERSIONS.c.version).label("latest_version"),
                latest_difficulty.label("latest_difficulty"),
                *_category_fact_columns(),
            )
            .select_from(
                _SCENARIOS.outerjoin(_VERSIONS, _VERSIONS.c.scenario_id == _SCENARIOS.c.id)
            )
            .where(*archived_filter)
            .group_by(_SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru)
            .order_by(_SCENARIOS.c.slug)
            .limit(limit)
            .offset(offset)
        )
        listings = [
            StoredScenarioListing(
                scenario_id=ScenarioId(UUID(str(row.id))),
                slug=row.slug,
                title_ru=row.title_ru,
                archived_at=row.archived_at,
                version_count=int(row.version_count),
                latest_version=None if row.latest_version is None else int(row.latest_version),
                latest_difficulty=(
                    None if row.latest_difficulty is None else int(row.latest_difficulty)
                ),
                **_category_facts(row),
            )
            for row in result.all()
        ]
        return listings, total

    async def list_versions(
        self, scenario_id: ScenarioId
    ) -> list[StoredScenarioVersionDetail] | None:
        """Every version of one scenario, newest first; `None` when the scenario is unknown."""
        scenario = await self.get_scenario(scenario_id)
        if scenario is None:
            return None
        result = await self._session.execute(
            self._detail_select()
            .where(_VERSIONS.c.scenario_id == UUID(str(scenario_id)))
            .order_by(_VERSIONS.c.version.desc())
        )
        return [_version_detail(row) for row in result.all()]

    async def get_version_detail(
        self, scenario_version_id: ScenarioVersionId
    ) -> StoredScenarioVersionDetail | None:
        """One version's presentation projection, or `None`."""
        result = await self._session.execute(
            self._detail_select().where(_VERSIONS.c.id == UUID(str(scenario_version_id)))
        )
        row = result.one_or_none()
        return None if row is None else _version_detail(row)

    def _detail_select(self) -> sa.Select[Any]:
        """The `scenario_versions` presentation columns joined with the owning scenario's slug.

        `content` is deliberately absent: no listing endpoint may serialise a scenario document
        (D3, D4). Two derived facts are read out of it instead — the declared `variants` key and
        whether a prefab handoff exists — which is all `derive_scenario_variants` needs for the
        `ScenarioVariantsView` (HLD 70 §70.2.2).
        """
        return sa.select(
            _VERSIONS.c.id,
            _VERSIONS.c.scenario_id,
            _SCENARIOS.c.slug.label("scenario_slug"),
            _VERSIONS.c.schema_version,
            _VERSIONS.c.version,
            _VERSIONS.c.title,
            _VERSIONS.c.description,
            _VERSIONS.c.difficulty,
            _VERSIONS.c.role_chain,
            _VERSIONS.c.content_sha256,
            _VERSIONS.c.locked_at,
            _VERSIONS.c.created_at,
            _VERSIONS.c.content["variants"].label("declared_variants"),
            _VERSIONS.c.content["expected_response"]["prefab_handoff"].label("prefab_handoff"),
        ).select_from(_VERSIONS.join(_SCENARIOS, _SCENARIOS.c.id == _VERSIONS.c.scenario_id))

    async def add_scenario(self, scenario_id: ScenarioId, slug: str, title_ru: str) -> None:
        await self._session.execute(
            sa.insert(_SCENARIOS).values(id=UUID(str(scenario_id)), slug=slug, title_ru=title_ru)
        )

    async def find_version(
        self, scenario_id: ScenarioId, version: int
    ) -> StoredScenarioVersion | None:
        result = await self._session.execute(
            sa.select(
                _VERSIONS.c.id,
                _VERSIONS.c.scenario_id,
                _VERSIONS.c.version,
                _VERSIONS.c.content_sha256,
                _VERSIONS.c.locked_at,
            ).where(
                _VERSIONS.c.scenario_id == UUID(str(scenario_id)),
                _VERSIONS.c.version == version,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return StoredScenarioVersion(
            scenario_version_id=ScenarioVersionId(UUID(str(row.id))),
            scenario_id=ScenarioId(UUID(str(row.scenario_id))),
            version=int(row.version),
            content_sha256=row.content_sha256,
            locked_at=row.locked_at,
        )

    async def add_version(
        self,
        scenario_version: ScenarioVersion,
        content: Mapping[str, Any],
        content_sha256: str,
        source_path: str | None = None,
    ) -> None:
        values = scenario_version_row_values(scenario_version, content, content_sha256, source_path)
        await self._session.execute(sa.insert(_VERSIONS).values(**values))

    async def add_scoring_rules(
        self, scenario_version_id: ScenarioVersionId, rules: Sequence[ScoringRule]
    ) -> None:
        rows = scoring_rule_row_values(scenario_version_id, rules)
        if not rows:
            return
        await self._session.execute(sa.insert(_RULES), rows)

    async def lock_scenario_version(self, scenario_version_id: ScenarioVersionId) -> bool:
        """Set `locked_at = now()` if it is still null; `True` when this call set it (D4)."""
        result = await self._session.execute(
            sa.update(_VERSIONS)
            .where(
                _VERSIONS.c.id == UUID(str(scenario_version_id)),
                _VERSIONS.c.locked_at.is_(None),
            )
            .values(locked_at=sa.func.now())
            .returning(_VERSIONS.c.id)
        )
        return result.one_or_none() is not None

    # -- I4 E32: archive / unarchive (§20.11.3) ------------------------------------------------

    async def set_archived(
        self, scenario_id: ScenarioId, *, archived: bool
    ) -> StoredScenarioListing | None:
        """Idempotent: archiving only sets `archived_at` if it is still null; unarchiving always
        clears it. Returns the listing row after the change, or `None` if the scenario is
        unknown."""
        scenario_uuid = UUID(str(scenario_id))
        exists = await self._session.execute(
            sa.select(_SCENARIOS.c.id).where(_SCENARIOS.c.id == scenario_uuid)
        )
        if exists.one_or_none() is None:
            return None
        if archived:
            await self._session.execute(
                sa.update(_SCENARIOS)
                .where(_SCENARIOS.c.id == scenario_uuid, _SCENARIOS.c.archived_at.is_(None))
                .values(archived_at=sa.func.now())
            )
        else:
            await self._session.execute(
                sa.update(_SCENARIOS)
                .where(_SCENARIOS.c.id == scenario_uuid)
                .values(archived_at=None)
            )
        # A targeted re-read (not the paged helper): exactly one scenario matches this id.
        result = await self._session.execute(
            sa.select(
                _SCENARIOS.c.id,
                _SCENARIOS.c.slug,
                _SCENARIOS.c.title_ru,
                _SCENARIOS.c.archived_at,
                sa.func.count(_VERSIONS.c.id).label("version_count"),
                sa.func.max(_VERSIONS.c.version).label("latest_version"),
                *_category_fact_columns(),
            )
            .select_from(
                _SCENARIOS.outerjoin(_VERSIONS, _VERSIONS.c.scenario_id == _SCENARIOS.c.id)
            )
            .where(_SCENARIOS.c.id == scenario_uuid)
            .group_by(_SCENARIOS.c.id, _SCENARIOS.c.slug, _SCENARIOS.c.title_ru)
        )
        row = result.one()
        latest = _VERSIONS.alias("latest")
        difficulty_result = await self._session.execute(
            sa.select(latest.c.difficulty)
            .where(latest.c.scenario_id == scenario_uuid)
            .order_by(latest.c.version.desc())
            .limit(1)
        )
        latest_difficulty = difficulty_result.scalar_one_or_none()
        return StoredScenarioListing(
            scenario_id=ScenarioId(UUID(str(row.id))),
            slug=row.slug,
            title_ru=row.title_ru,
            archived_at=row.archived_at,
            version_count=int(row.version_count),
            latest_version=None if row.latest_version is None else int(row.latest_version),
            latest_difficulty=None if latest_difficulty is None else int(latest_difficulty),
            **_category_facts(row),
        )


def _version_detail(row: sa.Row[tuple[Any, ...]]) -> StoredScenarioVersionDetail:
    """One `scenario_versions` row (joined with its scenario's slug) as the read projection."""
    return StoredScenarioVersionDetail(
        scenario_version_id=ScenarioVersionId(UUID(str(row.id))),
        scenario_id=ScenarioId(UUID(str(row.scenario_id))),
        scenario_slug=str(row.scenario_slug),
        schema_version=int(row.schema_version),
        version=int(row.version),
        title=str(row.title),
        description=str(row.description),
        difficulty=int(row.difficulty),
        role_chain=tuple(RoleType(value) for value in row.role_chain),
        content_sha256=str(row.content_sha256),
        locked_at=row.locked_at,
        created_at=row.created_at,
        variants=derive_scenario_variants(
            schema_version=int(row.schema_version),
            role_chain=tuple(RoleType(value) for value in row.role_chain),
            has_prefab_handoff=row.prefab_handoff is not None,
            declared=(
                ScenarioVariants.model_validate(row.declared_variants)
                if row.declared_variants is not None
                else None
            ),
        ),
    )
