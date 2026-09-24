"""The five layer copy functions (HLD `10-domain-model.md` §10.3, §10.7, D3, SPEC §3, §10).

Conversion between the four information layers is never automatic and never aliased: it happens
only here, in one named function per direction, and always as an explicit deep copy. Nothing
mutable is shared between an input and its output.

There is deliberately **no** function whose input is `WorldTruth` or `CallerBelief` and whose
output is an `OperatorCard`, a `HandoffSnapshot` or a `DDSAssignment` (SPEC §3: "DDS MUST receive
'72'. It MUST NOT obtain '27' from WorldTruth"). The five functions below are the complete set,
and `backend/tests/unit/domain/scenario/` asserts that `snapshot_to_assignment` and
`snapshot_to_assignments` have no parameter through which a `WorldTruth` could arrive.

HLD gap — identity arguments: §10.3 fixes these four signatures literally, and neither
`freeze_card_to_snapshot` nor `snapshot_to_assignment` receives the id of the aggregate it
creates, although `HandoffSnapshot.snapshot_id` and `DDSAssignment.assignment_id` are required
(§10.7). The domain is pure and may not invent randomness (D2/D7), so both ids are derived
deterministically with `uuid5` from the inputs that identify the new object: the same card
revision always freezes to the same snapshot id, and the same (snapshot, role stage) pair always
yields the same assignment id — which is also what D7's replay determinism wants.

HLD gap — one assignment per recipient service: §10.7 says "one assignment per recipient service",
while §10.3's `snapshot_to_assignment` returns a single `DDSAssignment`. SPEC §10 step 6 says
"Create the DDS work item from the snapshot" (singular). E9 reconciles the two rather than
choosing between them (E9 analyst §1, rules R2/R3): there is **one** work item, owned by the DDS
`RoleStage` and addressed to N recipient services, and each `DDSAssignment` row is that work
item's *leg* for one receiving service. `snapshot_to_assignment` keeps its §10.3 signature and
keeps building the leg of the first recipient service; `snapshot_to_assignments` — additive to
§10.3, a fifth copy function — builds all N legs, in `snapshot.recipient_services` order.

The two derive their `assignment_id` differently, and deliberately so: the fan-out puts the
service type inside the `uuid5` name, because without it the N legs of one (snapshot, role stage)
pair would all collide on a single id. `snapshot_to_assignment` is left exactly as it was — a unit
test pins its parameter list and its determinism — so the two functions agree on every field
except that id. The handoff use case persists the fan-out; nothing persists the singular one.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import UUID, uuid5

from app.domain.caller.emotion import EmotionState
from app.domain.common.ids import (
    AssignmentId,
    CardRevisionId,
    IncidentId,
    RoleStageId,
    SnapshotId,
    UserId,
)
from app.domain.common.values import FactValue
from app.domain.dds.assignment import DDSAssignment
from app.domain.enums import DDSStageState, ServiceId
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.layers.operator_card import OperatorCard
from app.domain.layers.world_truth import WorldTruth
from app.domain.scenario.version import ScenarioVersion

_ID_NAMESPACE = UUID("6f1f2e5c-9a4d-5f3b-8c21-6b0f6d3a1e77")
"""Fixed uuid5 namespace for the derived snapshot/assignment ids (see the module docstring)."""

__all__ = [
    "freeze_card_to_snapshot",
    "instantiate_caller_belief",
    "instantiate_world_truth",
    "snapshot_to_assignment",
    "snapshot_to_assignments",
]


def _canonical_json(card_values: dict[str, FactValue], services: tuple[ServiceId, ...]) -> str:
    """Canonical JSON over `card_values` + `recipient_services` (§10.7 `content_sha256`)."""
    return json.dumps(
        {
            "card_values": card_values,
            "recipient_services": list(services),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def instantiate_world_truth(version: ScenarioVersion, incident_id: IncidentId) -> WorldTruth:
    """Deep-copy the scenario's `world_truth.facts` into a fresh `WorldTruth` (§10.3, D3)."""
    return WorldTruth(
        incident_id=incident_id,
        revision=0,
        facts={
            fact_id: deepcopy(spec.world_value)
            for fact_id, spec in version.world_truth.facts.items()
        },
        value_types={
            fact_id: spec.value_type for fact_id, spec in version.world_truth.facts.items()
        },
    )


def instantiate_caller_belief(version: ScenarioVersion, incident_id: IncidentId) -> CallerBelief:
    """Deep-copy the scenario's `caller_knowledge.facts` into a fresh `CallerBelief` (§10.3, D3).

    The caller's emotion starts at the profile's `baseline_emotion` / `baseline_stress_level`
    (D4: `current_emotion` and `stress_level` are simulation state, not scenario keys), and
    `revealed_fact_ids` starts empty — it is maintained by `FACTS_DELIVERED` only (D10).

    The world's values never enter this structure: only `caller_knowledge` is read, so a fact the
    caller does not know (`incident.fire_source`) carries `None` here and its world value cannot
    leak into the caller's LLM context (SPEC §5).
    """
    facts = version.caller_knowledge.facts
    return CallerBelief(
        incident_id=incident_id,
        revision=0,
        facts={fact_id: deepcopy(spec.caller_value) for fact_id, spec in facts.items()},
        knowledge={fact_id: spec.knowledge for fact_id, spec in facts.items()},
        certainty={fact_id: spec.certainty for fact_id, spec in facts.items()},
        emotion=EmotionState(
            emotion=version.caller_profile.baseline_emotion,
            stress_level=version.caller_profile.baseline_stress_level,
        ),
        revealed_fact_ids=frozenset(),
    )


def freeze_card_to_snapshot(
    card: OperatorCard,
    card_revision_id: CardRevisionId,
    recipient_services: tuple[ServiceId, ...],
    created_by_user_id: UserId,
    at_offset_ms: int,
) -> HandoffSnapshot:
    """Freeze exactly what the trainee entered into an immutable snapshot (§10.3, §10.7, SPEC §10).

    The snapshot is a deep copy of `card.values`: later card edits cannot reach it, and the
    snapshot holds the card's value even where that value contradicts world truth.
    """
    card_values: dict[str, FactValue] = deepcopy(dict(card.values))
    services = tuple(recipient_services)
    payload = _canonical_json(card_values, services)
    return HandoffSnapshot(
        snapshot_id=SnapshotId(uuid5(_ID_NAMESPACE, f"snapshot:{card.card_id}:{card_revision_id}")),
        incident_id=card.incident_id,
        card_id=card.card_id,
        card_revision_id=card_revision_id,
        card_values=card_values,
        recipient_services=services,
        created_by_user_id=created_by_user_id,
        created_at_offset_ms=at_offset_ms,
        content_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def snapshot_to_assignment(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId, at_offset_ms: int
) -> DDSAssignment:
    """Create the DDS work item from the snapshot and from nothing else (§10.3, §10.7, SPEC §10).

    The parameter list is the whole point of this function: there is no `WorldTruth` parameter, so
    the DDS work item structurally cannot carry a value the operator did not enter. What the DDS
    trainee reads is `snapshot.card_values` via `snapshot_id`.

    See the module docstring for the `service_type` / multi-service reading: this function builds
    the leg of the **first** recipient service; `snapshot_to_assignments` builds all of them.
    """
    if not snapshot.recipient_services:
        raise ValueError(
            f"handoff snapshot {snapshot.snapshot_id} has no recipient_services to assign to"
        )
    return DDSAssignment(
        assignment_id=AssignmentId(
            uuid5(_ID_NAMESPACE, f"assignment:{snapshot.snapshot_id}:{role_stage_id}")
        ),
        incident_id=snapshot.incident_id,
        role_stage_id=role_stage_id,
        snapshot_id=snapshot.snapshot_id,
        service_type=snapshot.recipient_services[0],
        state=DDSStageState.RECEIVED,
        received_at_offset_ms=at_offset_ms,
    )


def snapshot_to_assignments(
    snapshot: HandoffSnapshot, role_stage_id: RoleStageId, at_offset_ms: int
) -> tuple[DDSAssignment, ...]:
    """One `DDSAssignment` leg per recipient service, in `recipient_services` order (§10.7).

    The parameter list is deliberately the same three as `snapshot_to_assignment`'s: there is no
    `WorldTruth` parameter here either, so no leg can carry a value the operator did not enter.

    Every leg starts in `DDSStageState.RECEIVED`, which is the DDS stage's own initial state — so
    the "`role_stages.state` is the authority, `dds_assignments.state` mirrors it" rule holds from
    the moment the legs exist. The ids are derived with `uuid5` from `(snapshot, role stage,
    service type)`: the service type is part of the name because the N legs of one handoff share
    the other two components and would otherwise all be the same id.
    """
    if not snapshot.recipient_services:
        raise ValueError(
            f"handoff snapshot {snapshot.snapshot_id} has no recipient_services to assign to"
        )
    return tuple(
        DDSAssignment(
            assignment_id=AssignmentId(
                uuid5(
                    _ID_NAMESPACE,
                    f"assignment:{snapshot.snapshot_id}:{role_stage_id}:{service_type}",
                )
            ),
            incident_id=snapshot.incident_id,
            role_stage_id=role_stage_id,
            snapshot_id=snapshot.snapshot_id,
            service_type=service_type,
            state=DDSStageState.RECEIVED,
            received_at_offset_ms=at_offset_ms,
        )
        for service_type in snapshot.recipient_services
    )
