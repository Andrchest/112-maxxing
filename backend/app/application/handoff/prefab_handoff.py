"""The scenario's prefab handoff, materialised when a DDS-only chain starts (D6, §30.5, §10.10).

Two ways reach it (HLD 70 §70.2.4): a scenario whose `role_chain` is `[DDS]`, and any scenario run
under `card_source: GENERATED_CARD`, whose **effective** chain is the suffix starting at DDS — on
the demo, `[OPERATOR_112, DDS]` runs as `[DDS]`. Either way the session's first stage is DDS and
this module does exactly the same thing; it never reads the variants itself.

A `role_chain` of `[DDS]` has no Operator 112 stage, so nothing produces the `HandoffSnapshot`
the DDS work item is built from. D6 answers that with `expected_response.prefab_handoff`: a
scenario-authored 112 handoff, "deliberately imperfect where the exercise wants it to be"
(§30.5) — the demo's prefab carries the caller's wrong floor, and rule R14 checks its
`card_values` against `CARD_FIELDS` but never against world truth. A `SINGLE_ROLE` or
`ASSESSMENT` session on a DDS-first scenario without one is refused at *creation* with
`409 PREFAB_HANDOFF_REQUIRED` (`app.domain.session.session.create_session`), so by the time this
module runs the prefab is known to exist.

**When:** at DDS stage start, which for a DDS-only chain is `startSession` — the same moment
`ROLE_STAGE_STARTED` is appended for that stage. Not at session creation: a `READY` session has
no timeline yet (D7), and a snapshot stamped with an offset from before the session started would
be a handoff that happened before the exercise did.

**What it writes,** all inside `startSession`'s single Unit of Work:

1. the prefab's `card_values` onto the incident's (empty) `OperatorCard`, one `set_field` per
   path, authored by the **instructor who created the session** — the closest true actor, since
   the 112 operator whose work this represents does not exist in this session. Each write makes a
   normal `incident_card_revisions` row and a normal `CARD_FIELD_CHANGED`, so the snapshot's
   `card_revision_id` points at a real revision and the card the instructor console shows is the
   card the snapshot froze. This is why this module is on INV 4's card-writer allow-list, and it
   is also why it imports nothing transcript-, ASR- or voice-related: the prefab comes from the
   scenario file and from nowhere else;
2. the `HandoffSnapshot` itself, through the same `freeze_card_to_snapshot` the real handoff
   uses — same deep copy, same `content_sha256`;
3. one `DDSAssignment` leg per recipient service, through the same `snapshot_to_assignments`;
4. one `HANDOFF_RECEIVED` (`SIMULATION`) per leg.

**No `HANDOFF_CREATED`.** §10.13 types that event `TRAINEE`-only, and no trainee created this
handoff; writing it with a `SIMULATION` actor would put a trainee action in the audit log that
nobody performed (SPEC §8). The analyst's §7 #15 notes that E15's `ScoringContext` reads the
handoff payload from `HANDOFF_CREATED`, which means a DDS-only session has no 112 handoff to
score — which is correct: there was no 112 stage to score. E17/E15 own whatever a DDS-only report
says about it.

`WorldTruth` is not reachable from here: the only scenario section this module reads is
`expected_response.prefab_handoff`, and it is handed in already extracted.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from app.application.ports.id_generator import IdGenerator
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.common.actors import ActorRef
from app.domain.common.errors import DomainError
from app.domain.common.ids import CardRevisionId, IncidentId, RoleStageId
from app.domain.common.values import FactValue
from app.domain.enums import ActorType, ValueType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType
from app.domain.layers.card_schema import CardSchema
from app.domain.layers.copies import freeze_card_to_snapshot, snapshot_to_assignments
from app.domain.layers.operator_card import OperatorCard, set_field
from app.domain.scenario.sections import PrefabHandoff
from app.domain.session.session import SimulationSession

__all__ = ["PrefabCardMissingError", "materialise_prefab_handoff"]

_SIMULATION = ActorRef(actor_type=ActorType.SIMULATION)
"""`HANDOFF_RECEIVED`'s actor (§10.13)."""

SERVICES_FIELD_PATH = "recipients.services"
"""The `CARD_FIELDS` path the recipient services live in (§10.6).

Spelled out here rather than imported from `app.application.operator.select_service`, which holds
the same constant: importing that module would pull in the whole Operator 112 package, and
`app.application.sessions.start_session` — this module's only caller — is itself imported by it.
The path is `CARD_FIELDS` data either way, and `test_prefab_handoff.py` pins the two equal.
"""


class PrefabCardMissingError(DomainError):
    """The incident has no `incident_cards` row — session creation always makes one (`404`)."""

    code = "NOT_FOUND"

    def __init__(self, incident_id: IncidentId) -> None:
        self.incident_id = incident_id
        super().__init__(f"incident {incident_id} has no operator card to build a prefab on")


async def materialise_prefab_handoff(
    uow: UnitOfWork,
    session: SimulationSession,
    prefab: PrefabHandoff,
    role_stage_id: RoleStageId,
    *,
    ids: IdGenerator,
    now_ms: int,
    card_schema: CardSchema | None = None,
) -> list[DomainEvent]:
    """Write the prefab card, snapshot and legs; return the events the caller appends.

    `card_schema` is the version's card schema (I3 E3a, HLD 70 §70.5.4; `v1` when omitted): a
    schema-2 prefab writes v2 paths, which is how a GENERATED_CARD session reaches the ДДС in the
    v2 layout.

    The events come back rather than being appended here so that the caller keeps them in the
    right order relative to its own (`SESSION_STARTED`, `ROLE_STAGE_STARTED`): the DDS stage must
    be started before it is handed anything.
    """
    incident_id = session.incident.incident_id
    card = await uow.operator_cards.get(incident_id)
    if card is None:  # pragma: no cover - `create_session` always inserts one
        raise PrefabCardMissingError(incident_id)

    author = ActorRef(actor_type=ActorType.INSTRUCTOR, actor_id=session.created_by_user_id)
    card, revision_id, card_events = await _write_prefab_card(
        uow, card, _prefab_values(prefab), author, ids=ids, now_ms=now_ms, schema=card_schema
    )
    if revision_id is None:  # pragma: no cover - rule R14 forbids an empty prefab card
        raise PrefabCardMissingError(incident_id)

    snapshot = freeze_card_to_snapshot(
        card, revision_id, tuple(prefab.recipient_services), session.created_by_user_id, now_ms
    )
    legs = snapshot_to_assignments(snapshot, role_stage_id, now_ms)
    await uow.handoffs.add(snapshot)
    await uow.dds_assignments.add_all(legs)

    return [
        *card_events,
        *(
            DomainEvent(
                event_type=EventType.HANDOFF_RECEIVED,
                actor=_SIMULATION,
                monotonic_offset_ms=now_ms,
                payload={
                    "snapshot_id": UUID(str(snapshot.snapshot_id)),
                    "assignment_id": UUID(str(leg.assignment_id)),
                    "role_stage_id": UUID(str(leg.role_stage_id)),
                    "service_type": leg.service_type,
                    "at_offset_ms": now_ms,
                },
            )
            for leg in legs
        ),
    ]


def _prefab_values(prefab: PrefabHandoff) -> dict[str, FactValue]:
    """The prefab's `card_values`, with `recipients.services` guaranteed to match its recipients.

    §30.5 keeps the two side by side and rule R14 does not tie them together, so a prefab may name
    its recipients only in `recipient_services`. The card field is what
    `guard_at_least_one_recipient_service` and the report read, so it is filled from the
    authoritative list — and overwritten when the file disagrees with itself, because
    `recipient_services` is the key the snapshot is built from.
    """
    values: dict[str, FactValue] = dict(prefab.card_values)
    values[SERVICES_FIELD_PATH] = list(prefab.recipient_services)
    return values


async def _write_prefab_card(
    uow: UnitOfWork,
    card: OperatorCard,
    values: Mapping[str, FactValue],
    author: ActorRef,
    *,
    ids: IdGenerator,
    now_ms: int,
    schema: CardSchema | None = None,
) -> tuple[OperatorCard, CardRevisionId | None, list[DomainEvent]]:
    """One `set_field` per prefab path, in file order.

    Returns the written card, the id of the last revision it made, and the events.
    """
    events: list[DomainEvent] = []
    last_revision_id: CardRevisionId | None = None
    for field_path, value in values.items():
        card, revision, card_event = set_field(
            card, field_path, value, author, now_ms, CardRevisionId(ids.new()), schema=schema
        )
        if revision is None or card_event is None:
            continue
        value_type = card_event.payload["value_type"]
        assert isinstance(value_type, ValueType)
        await uow.operator_cards.add_revision(revision, value_type)
        last_revision_id = revision.revision_id
        events.append(card_event)
    await uow.operator_cards.save(card)
    return card, last_revision_id, events
