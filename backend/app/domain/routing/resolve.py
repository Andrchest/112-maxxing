"""The routing resolver and the notification list (HLD `70-i3-alignment.md` §70.6.4, D18, A-1).

`resolve_notification_list(classifier, catalog, card_values, schema=...)` is **pure**: a table
lookup over the classifier v_046_24, the service catalog and the card's own values. The LLM never
sees the card (SPEC §2, C11) and nothing here writes the card — the application records the
result as a SIMULATION `RECIPIENTS_RESOLVED` event (INV 4, D3).

The three steps (§70.6.4, the resolver defaults of B1 §4 and the manager's step-1 fallback):

1. **Candidate rows.** `incident.classifier_code` naming a classifier row wins: that row alone.
   Otherwise every selected «Что случилось» entry (`incident.types`, not `routing: none`, A-3)
   opens its classifier group — the part of its code before `:` (D21). Per group, the candidates
   are the rows whose every признак (`features`) is covered by the card's codes (`COVERED`). A
   group with no covered row falls back to its rows **consistent** with the card: every card code
   that is a признак of that group appears among the row's признаки (`GROUP_FALLBACK`) — the 104
   and «Взрыв» questionnaires are authored to the first question level only, so full coverage
   reaches almost nothing there. A group the card says nothing about (no card code is one of its
   признаки) yields no candidate: an empty questionnaire is not evidence for every row of the
   group. One candidate ⇒ `classifier_code`; several ⇒ `candidate_codes`, and `auto_services` is
   the union of their routing until the operator sets `incident.classifier_code`.
2. **Orgs.** A flag (`no_access`, `threat_to_people`, …) is true iff its key is among the card's
   codes; a flag no field carries is false. An org is notified iff **any** of its sub-columns
   whose `when` holds has a cell that counts (A-1: non-empty and not «нет реагирования»);
   `reasons.sub_column` names the first such column letter.
3. **Territorial ДДС.** «Территориальные ОИВ» (BW; BX when `address.okrug` = ТиНАО) counting ⇒
   the `DISTRICT` entry whose `district` is `address.district` and the `PREFECTURE` entry whose
   `okrug` is `address.okrug`; an absent value means that leg is absent.

An org maps to the catalog entry whose `classifier_org_ids` names it (`FIRE_RESCUE` answers to
both «Служба 101» and «ОДС ПСЦ»). A `display: false` entry goes to `informed_services`
(REQ-5280), never to the notification list or a leg.

A card code is what the binding of 70 §70.5.2 says it is: an option's `code` (its
`classifier_features` when it stands for several признаки), a BOOLEAN toggle's single option when
the toggle is on. Matching is casefolded and whitespace-collapsed; labels are never read.

"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.common.actors import ActorRef
from app.domain.common.values import FactValue
from app.domain.enums import ActorType, ServiceId, ValueType
from app.domain.events.session_event import DomainEvent, SessionEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardOption, CardSchema
from app.domain.routing.catalog import (
    ReferenceCatalog,
    ServiceCatalog,
    ServiceCatalogEntry,
    ServiceKind,
)
from app.domain.routing.classifier import Classifier, ClassifierRow

__all__ = [
    "CLASSIFIER_CODE_PATH",
    "DISTRICT_PATH",
    "EMPTY_RESOLUTION",
    "INCIDENT_TYPES_PATH",
    "OKRUG_PATH",
    "PackRouting",
    "ReasonSource",
    "Resolution",
    "RoutingReason",
    "RowMatch",
    "last_resolution",
    "notification_list",
    "pack_routing",
    "recipients_resolved_event",
    "resolve_notification_list",
]

INCIDENT_TYPES_PATH = "incident.types"
CLASSIFIER_CODE_PATH = "incident.classifier_code"
OKRUG_PATH = "address.okrug"
DISTRICT_PATH = "address.district"

_TERRITORIAL_ORG = "TERRITORIAL_OIV"
"""Column BW «Территориальные ОИВ» — every okrug but ТиНАО, and a card with no okrug."""
_TERRITORIAL_ORG_TINAO = "TERRITORIAL_OIV_TINAO"
"""Column BX «Территориальные ОИВ ТиНАО»."""
_TERRITORIAL_ORGS = frozenset({_TERRITORIAL_ORG, _TERRITORIAL_ORG_TINAO})
_TINAO = "ТиНАО"

_MAIN_SERVICE_IDS: Mapping[str, str] = {
    "MCHS": "FIRE_RESCUE",
    "POLICE": "POLICE",
    "AMBULANCE": "AMBULANCE",
    "MOSGAZ": "GAS_SERVICE",
    "MOSLIFT": "MOSLIFT",
    "AUTOROADS": "AVTODOROGI",
    "MOSVODOCANAL": "MOSVODOKANAL",
    "METRO": "METRO",
    "OEK": "OEK",
    "MOSGORTRANS": "MOSGORTRANS",
    "MOESK": "ROSSETI_MR",
    "MOEK": "MOEK",
    "MZD": "MZHD",
    "MGTS": "MGTS",
    "MOSVODOSTOK": "MOSVODOSTOK",
    "MOSCOLLECTOR": "MOSKOLLEKTOR",
    "GORMOST": "GORMOST",
    "DEP.TSZN": "DEP_TSZN",
    "ZODD": "TSODD",
    "MSPPN": "MSPPN",
    "ZEMP": "TSEMP",
    "МСР": "GUP_MSR",
}
"""The classifier's «Основная служба» tokens (column `main_service`, upper-cased) → catalog ids.
A composite token (`METRO, MZD`) takes its first member; `GKH` and `DepEco` name no single
catalog entry and resolve to `null` (recorded in the E2b′ report)."""

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)


class ReasonSource(str, Enum):
    """`RECIPIENTS_RESOLVED.reasons[].source` (§70.7)."""

    CLASSIFIER = "CLASSIFIER"
    TERRITORIAL = "TERRITORIAL"
    DEPARTMENT = "DEPARTMENT"


class RowMatch(str, Enum):
    """How the classifier row behind a reason was found (additive, manager decision on E2b′):
    the operator's «Класс.:» pick, full coverage by the card's codes, or the group fallback."""

    CLASSIFIER_CODE = "CLASSIFIER_CODE"
    COVERED = "COVERED"
    GROUP_FALLBACK = "GROUP_FALLBACK"


class RoutingReason(BaseModel):
    """Why one service is on the list: the org column group, its first counting sub-column, and
    the classifier row (and how that row was matched)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service_id: ServiceId
    source: ReasonSource
    column: str
    sub_column: str | None
    row_code: str
    row_match: RowMatch


class Resolution(BaseModel):
    """The resolver's answer (the resolver half of `RECIPIENTS_RESOLVED`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    classifier_code: str | None = None
    candidate_codes: tuple[str, ...] = ()
    main_service: ServiceId | None = None
    auto_services: tuple[ServiceId, ...] = ()
    informed_services: tuple[ServiceId, ...] = ()
    reasons: tuple[RoutingReason, ...] = ()

    @property
    def group_fallback_used(self) -> bool:
        return any(reason.row_match is RowMatch.GROUP_FALLBACK for reason in self.reasons)


EMPTY_RESOLUTION = Resolution()


@dataclass(frozen=True, slots=True)
class PackRouting:
    """What the resolver needs of a session's reference pack; only a pack with a classifier has
    routing (`legacy-r1` has none, so a v1 session keeps manual selection only)."""

    pack_id: str
    classifier: Classifier
    catalog: ServiceCatalog
    schema: CardSchema

    def resolve(self, card_values: Mapping[str, FactValue]) -> Resolution:
        return resolve_notification_list(
            self.classifier, self.catalog, card_values, schema=self.schema
        )


def pack_routing(reference: ReferenceCatalog, pack_id: str) -> PackRouting | None:
    """The routing of `pack_id`, or `None` for an unknown pack or a pack without a classifier."""
    classifier = reference.classifier(pack_id)
    catalog = reference.services(pack_id)
    schema = reference.card_schema(pack_id)
    if classifier is None or catalog is None or schema is None:
        return None
    return PackRouting(pack_id=pack_id, classifier=classifier, catalog=catalog, schema=schema)


# ---------------------------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class _CardCodes(BaseModel):
    model_config = ConfigDict(frozen=True)

    groups: tuple[int, ...]
    features: frozenset[str]
    flags: frozenset[str]


def _selected_options(
    spec_options: Sequence[CardOption], value_type: ValueType, value: Any
) -> list[CardOption]:
    by_code = {option.code: option for option in spec_options}
    if value_type is ValueType.BOOLEAN:
        return list(spec_options) if value is True else []
    items = value if isinstance(value, list) else [value]
    return [by_code[item] for item in items if isinstance(item, str) and item in by_code]


def _card_codes(
    schema: CardSchema, card_values: Mapping[str, FactValue], flag_keys: frozenset[str]
) -> _CardCodes:
    groups: list[int] = []
    features: set[str] = set()
    flags: set[str] = set()
    for spec in schema.fields:
        if not spec.routing_relevant or spec.options is None:
            continue
        if spec.field_path in (OKRUG_PATH, DISTRICT_PATH, CLASSIFIER_CODE_PATH):
            continue
        value = card_values.get(spec.field_path)
        if value is None:
            continue
        for option in _selected_options(spec.options, spec.value_type, value):
            if option.routing == "none":
                continue
            if spec.field_path == INCIDENT_TYPES_PATH:
                group = option.code.split(":", 1)[0]
                if group.isdigit() and int(group) not in groups:
                    groups.append(int(group))
                # An entry's own code is a group, not a признак; only listed признаки narrow.
                features.update(_norm(text) for text in option.classifier_features or ())
            elif option.code in flag_keys:
                flags.add(option.code)
            else:
                features.update(_norm(text) for text in option.classifier_feature_texts)
    return _CardCodes(groups=tuple(groups), features=frozenset(features), flags=frozenset(flags))


def _row_features(row: ClassifierRow) -> tuple[str, ...]:
    return tuple(_norm(feature) for feature in row.features if feature.strip())


def _candidates(
    classifier: Classifier, codes: _CardCodes, classifier_code: str | None
) -> list[tuple[ClassifierRow, RowMatch]]:
    if classifier_code is not None:
        row = classifier.row(classifier_code)
        if row is not None:
            return [(row, RowMatch.CLASSIFIER_CODE)]
    found: list[tuple[ClassifierRow, RowMatch]] = []
    for group in codes.groups:
        rows = [(row, _row_features(row)) for row in classifier.rows if row.group_no == group]
        covered = [row for row, feats in rows if feats and all(f in codes.features for f in feats)]
        if covered:
            found.extend((row, RowMatch.COVERED) for row in covered)
            continue
        group_texts = {f for _row, feats in rows for f in feats}
        group_codes = codes.features & group_texts
        if not group_codes:
            continue
        found.extend(
            (row, RowMatch.GROUP_FALLBACK) for row, feats in rows if group_codes <= set(feats)
        )
    return found


def _counting_sub_column(
    classifier: Classifier, org_id: str, cells: Sequence[Any], flags: frozenset[str]
) -> tuple[bool, str | None]:
    """(notified, first counting sub-column letter) — A-1 over every holding sub-column."""
    org = next((org for org in classifier.orgs if org.org_id == org_id), None)
    for index, cell in enumerate(cells):
        holds = all((key in flags) == wanted for key, wanted in cell.when.items())
        if holds and cell.counts:
            column = (
                org.sub_columns[index].column
                if org is not None and index < len(org.sub_columns)
                else None
            )
            return True, column
    return False, None


def _org_entries(catalog: ServiceCatalog) -> dict[str, ServiceCatalogEntry]:
    entries: dict[str, ServiceCatalogEntry] = {}
    for entry in catalog.services:
        org_ids = entry.classifier_org_ids or (
            (entry.classifier_org_id,) if entry.classifier_org_id else ()
        )
        for org_id in org_ids:
            entries.setdefault(org_id, entry)
    return entries


def _str_value(value: FactValue) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _main_service(rows: Sequence[ClassifierRow], catalog: ServiceCatalog) -> ServiceId | None:
    mapped: set[str | None] = set()
    for row in rows:
        token = (row.main_service or "").split(",", 1)[0].strip().upper()
        service = _MAIN_SERVICE_IDS.get(token)
        mapped.add(service if service is not None and service in catalog else None)
    if len(mapped) != 1:
        return None
    only = mapped.pop()
    return ServiceId(only) if only is not None else None


def resolve_notification_list(
    classifier: Classifier,
    catalog: ServiceCatalog,
    card_values: Mapping[str, FactValue],
    *,
    schema: CardSchema,
) -> Resolution:
    """§70.6.4 steps 1–3 over the card's values (see the module docstring). Pure and total.

    `schema` is the session's card schema: it says which paths are routing-relevant and what
    each option code stands for (its `classifier_features`) — additive to the HLD's
    three-argument signature, because codes alone cannot say which chip lists several признаки.
    """
    flag_keys = frozenset(
        key for org in classifier.orgs for sub in org.sub_columns for key in sub.when
    )
    codes = _card_codes(schema, card_values, flag_keys)
    candidates = _candidates(classifier, codes, _str_value(card_values.get(CLASSIFIER_CODE_PATH)))
    if not candidates:
        return EMPTY_RESOLUTION

    okrug = _str_value(card_values.get(OKRUG_PATH))
    district = _str_value(card_values.get(DISTRICT_PATH))
    territorial_org = _TERRITORIAL_ORG_TINAO if okrug == _TINAO else _TERRITORIAL_ORG
    org_entries = _org_entries(catalog)

    reasons: dict[str, RoutingReason] = {}

    def add(entry: ServiceCatalogEntry, reason: dict[str, Any]) -> None:
        if entry.id not in reasons:
            reasons[entry.id] = RoutingReason(service_id=entry.id, **reason)

    for row, match in candidates:
        for org_id, cells in row.routing.items():
            if org_id in _TERRITORIAL_ORGS and org_id != territorial_org:
                continue
            notified, sub_column = _counting_sub_column(classifier, org_id, cells, codes.flags)
            if not notified:
                continue
            base = {
                "column": org_id,
                "sub_column": sub_column,
                "row_code": row.code,
                "row_match": match,
            }
            if org_id in _TERRITORIAL_ORGS:
                for dds in catalog.services:
                    if (
                        dds.kind is ServiceKind.DISTRICT
                        and district is not None
                        and dds.district == district
                    ) or (
                        dds.kind is ServiceKind.PREFECTURE
                        and okrug is not None
                        and dds.okrug == okrug
                    ):
                        add(dds, {**base, "source": ReasonSource.TERRITORIAL})
                continue
            entry = org_entries.get(org_id)
            if entry is None:  # impossible after E3a′ (every column group has an entry)
                continue
            source = (
                ReasonSource.DEPARTMENT
                if entry.kind is ServiceKind.DEPARTMENT
                else ReasonSource.CLASSIFIER
            )
            add(entry, {**base, "source": source})

    ordered = [entry for entry in catalog.services if entry.id in reasons]
    rows = [row for row, _match in candidates]
    return Resolution(
        classifier_code=rows[0].code if len(rows) == 1 else None,
        candidate_codes=tuple(row.code for row in rows),
        main_service=_main_service(rows, catalog),
        auto_services=tuple(entry.id for entry in ordered if entry.display),
        informed_services=tuple(entry.id for entry in ordered if not entry.display),
        reasons=tuple(reasons[entry.id] for entry in ordered),
    )


# ---------------------------------------------------------------------------------------------
# The notification list and the event
# ---------------------------------------------------------------------------------------------


def notification_list(
    auto: Iterable[ServiceId], manual: Iterable[ServiceId]
) -> tuple[ServiceId, ...]:
    """auto ∪ manual (§70.6.4): the automatic services first, then the manual additions not
    already there, each in its own order."""
    result: list[ServiceId] = []
    for service in (*auto, *manual):
        if service not in result:
            result.append(service)
    return tuple(result)


def recipients_resolved_event(
    resolution: Resolution,
    *,
    card_id: UUID,
    card_revision_id: UUID | None,
    pack_id: str,
    manual_services: Sequence[ServiceId],
    final: bool,
    at_offset_ms: int,
) -> DomainEvent:
    """`RECIPIENTS_RESOLVED` (SIMULATION, §70.7) — the resolver's answer recorded, never a write
    into the card (INV 4, D3)."""
    return DomainEvent(
        event_type=EventType.RECIPIENTS_RESOLVED,
        actor=_SIMULATION,
        monotonic_offset_ms=at_offset_ms,
        payload={
            "card_id": card_id,
            "card_revision_id": card_revision_id,
            "pack_id": pack_id,
            "classifier_code": resolution.classifier_code,
            "candidate_codes": list(resolution.candidate_codes),
            "main_service": resolution.main_service,
            "auto_services": list(resolution.auto_services),
            "informed_services": list(resolution.informed_services),
            "manual_services": list(manual_services),
            "notification_list": list(notification_list(resolution.auto_services, manual_services)),
            "reasons": [reason.model_dump(mode="json") for reason in resolution.reasons],
            "final": final,
            "at_offset_ms": at_offset_ms,
        },
    )


def last_resolution(
    events: Iterable[SessionEvent], *, cutoff_seq_no: int | None = None
) -> SessionEvent | None:
    """The last `RECIPIENTS_RESOLVED` of the log (at or before `cutoff_seq_no`), or `None`."""
    found: SessionEvent | None = None
    for event in events:
        if event.event_type is not EventType.RECIPIENTS_RESOLVED:
            continue
        if cutoff_seq_no is not None and event.seq_no > cutoff_seq_no:
            continue
        found = event
    return found
