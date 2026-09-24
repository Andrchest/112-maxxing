"""The incident classifier v_046_24 as data (HLD `70-i3-alignment.md` §70.6.2, D18, A-1).

`reference/classifier/v046_24.json` holds one `ClassifierRow` per classifier row and
`v046_24.columns.json` the routing column map (`ClassifierOrg`); both are generated from the
organizer's xlsx by `backend/tools/import_classifier.py`. Each row's `routing[org_id]` is aligned
with that org's `sub_columns`, so a cell's source column is known without repeating it per row.

Pure: the resolver of §70.6.4 (E2b) and the reference API read these types; nothing here does I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr

__all__ = [
    "NO_RESPONSE_VALUE",
    "Classifier",
    "ClassifierOrg",
    "ClassifierRow",
    "ClassifierSubColumn",
    "RoutingCell",
    "cell_counts_as_notification",
]

NO_RESPONSE_VALUE = "нет реагирования"
"""The one non-empty routing value that is **not** a notification (assumption A-1)."""


def cell_counts_as_notification(value: str | None) -> bool:
    """A-1: a routing cell notifies its org iff it is non-empty and not «нет реагирования» —
    `карточка-112` and a labelled cell (`пожар: мусор`, `Травма`, …) both count."""
    return (
        value is not None and bool(value.strip()) and value.strip().casefold() != NO_RESPONSE_VALUE
    )


class RoutingCell(BaseModel):
    """One routing cell: the feature condition of its sub-column and the cell's value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    when: Mapping[str, bool]
    value: str | None

    @property
    def counts(self) -> bool:
        return cell_counts_as_notification(self.value)


class ClassifierRow(BaseModel):
    """One classifier row (§70.6.2; `openapi.yaml`'s `ClassifierRow`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    group_no: int
    group_ru: str
    features: tuple[str, ...]
    extra_features: tuple[str, ...]
    final_type_ru: str
    ekp35_ru: str | None
    main_service: str | None
    routing: Mapping[str, tuple[RoutingCell, ...]]


class ClassifierSubColumn(BaseModel):
    """One sub-column of an org's routing column group (source column letter, label, condition)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    column: str
    label_ru: str | None
    when: Mapping[str, bool]


class ClassifierOrg(BaseModel):
    """One routing column group of `v046_24.columns.json` (org id → name, sub-columns)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    org_id: str
    name_ru: str
    sub_columns: tuple[ClassifierSubColumn, ...]


class Classifier(BaseModel):
    """A classifier version: its rows in source order and its routing column map."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classifier_id: str
    rows: tuple[ClassifierRow, ...]
    orgs: tuple[ClassifierOrg, ...]

    _by_code: Mapping[str, ClassifierRow] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any, /) -> None:
        self._by_code = MappingProxyType({row.code: row for row in self.rows})

    def row(self, code: str) -> ClassifierRow | None:
        """The row with `code` («Номер»), or `None`."""
        return self._by_code.get(code)

    def search(
        self, query: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ClassifierRow], int]:
        """`(page, total)`: rows in source order whose code, category, признаки or final type
        contain `query` (case-insensitive; every row when blank), paged by `limit`/`offset`."""
        needle = (query or "").strip().casefold()
        matches = [row for row in self.rows if not needle or needle in _haystack(row)]
        return matches[offset : offset + limit], len(matches)


def _haystack(row: ClassifierRow) -> str:
    return " ".join(
        (row.code, row.group_ru, *row.features, *row.extra_features, row.final_type_ru)
    ).casefold()
