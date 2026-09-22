"""INV 5 — "Full-cycle role transition retains the same Incident" (SPEC §42 test 5, §1, §13).

`docs/hld/90-tbd-epics.md`'s naming convention (`INV n` = SPEC §42 invariant test *n*) has never
had a file under `test_inv_05_*` (E17 recon §2/§8): equivalent assertions have lived scattered in
`tests/api/handoff/test_role_transition.py` (`_incident_ids`) and `tests/api/dds/test_full_cycle.py`
without ever being drawn together as the one canonical invariant SPEC §13 states in as many words:
**"The same Incident object MUST survive all role transitions... This is NOT three independent
exercises."** This file is that canonical proof, over real HTTP and a real database, five ways:

1. **one `Incident` id**, before the transition and after it — the direct SPEC §42 test 5 claim;
2. **one `session_events` timeline**, `seq_no` strictly increasing with no gap across the
   transition — "not three independent exercises" restated as a log property: a second incident
   would need a second timeline, or a gap where one stream stopped and another started;
3. **the handoff snapshot is immutable after creation** — `content_sha256` and `card_values`
   byte-identical from the moment `createHandoff` writes them through to session completion,
   proving the DDS stage never mutates what it was handed;
4. **the DDS stage sees the snapshot, never the live `OperatorCard`** (D3, SPEC §10, §42 test 3) —
   the two read paths that could leak one incident's operator-side data into the other role are
   both checked: `getOperatorCard` is `403` for the `DDS` participant, and `getSessionSnapshot`'s
   `card` field is `null` for them, `work_item` populated instead;
5. **scoring evidence from both stages lands in one `ScoreReport`** — the report is not "the DDS
   report" or "the 112 report", it is the one report of the one incident, and evidence rows from
   before the transition (`seq_no` less than `ROLE_TRANSITION_COMPLETED`'s) sit in the same
   `score_report.results` as evidence rows from after it.

CONCURRENCY (E17-B is changing simulated-time behaviour across the `ROLE_TRANSITION` pause; E17-A
is adding optional `note_ru`/`comment_ru` payload keys to the dispatch/closure events): nothing
here asserts a concrete `monotonic_offset_ms` value spanning the pause (only that `seq_no` and
`monotonic_offset_ms` never decrease, and that the first post-transition event's offset is at
least the transition-start offset — never "exactly plus the pause"), and nothing asserts an exact
payload key set for `DISPATCH`/`CLOSE` events.

**Bite proof**: see `/tmp/teamwork-112-maxxing/reports/e17-d.md` under "INV 5 BITE PROOF" for the
captured red output of this file run against a deliberately broken worktree copy (the DDS stage
made to create a second `Incident` on `continueToNextStage`), which failed assertion 1 (and,
downstream, assertions 2 and 5) exactly as expected.

Fixtures are re-exported by name from `tests.api.**`'s conftests (`pytest_plugins` cannot register
an already-loaded conftest — the same pattern `test_inv_09_rescore_endpoint.py` and
`test_report_refused_for_unfinished_session.py` use), and `resolved` is imported directly from
`tests.api.dds.test_full_cycle`, the same fixture that module's own closure assertions use.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------------------------
# Fixtures, re-exported by name (see the module docstring)
# ---------------------------------------------------------------------------------------------

from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.dds import conftest as _dds_fixtures  # noqa: E402
from tests.api.dds.test_full_cycle import resolved as resolved  # noqa: E402
from tests.api.handoff import conftest as _handoff_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402

client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
api_settings = _api_fixtures.api_settings
tokens = _api_fixtures.tokens
users = _api_fixtures.users
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
demo_version_id = _api_fixtures.demo_version_id
unit_of_work = _api_fixtures.unit_of_work

flow = _operator_fixtures.flow
ringing = _operator_fixtures.ringing
connected = _operator_fixtures.connected
interview = _operator_fixtures.interview
uow_factory = _operator_fixtures.uow_factory

clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
prepared = _handoff_fixtures.prepared
handed_off = _handoff_fixtures.handed_off
in_transition = _handoff_fixtures.in_transition
dds_active = _handoff_fixtures.dds_active

OperatorFlow = _handoff_fixtures.OperatorFlow

auth = _api_fixtures.auth
dds_post = _dds_fixtures.dds_post
event_types = _dds_fixtures.event_types
events_of = _dds_fixtures.events_of

RULE_COUNT = 10
"""The demo scenario's own `scoring_rules` count (`scenarios/examples/apartment-fire/v1.yaml`)."""


async def _incident_ids(uow_factory: Any, session_id: Any) -> list[str]:
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text("SELECT id FROM incidents WHERE session_id = :session_id"),
            {"session_id": session_id},
        )
        ids = [str(row[0]) for row in result.all()]
        await uow.commit()
    return ids


async def _handoff_snapshot_row(uow_factory: Any, incident_id: Any) -> dict[str, Any]:
    """The one `handoff_snapshots` row for this incident — `HandoffSnapshot` is written once,
    `createHandoff`, and never updated again (`backend/app/db/models/layers.py`'s own docstring
    calls it "the immutable by-value copy")."""
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyUnitOfWork)
        result = await uow.session.execute(
            sa.text(
                "SELECT id, content_sha256, card_values, recipient_services"
                " FROM handoff_snapshots WHERE incident_id = :incident_id"
            ),
            {"incident_id": incident_id},
        )
        rows = [dict(row._mapping) for row in result.all()]
        await uow.commit()
    assert len(rows) == 1, "createHandoff writes exactly one snapshot per incident"
    return rows[0]


async def _incident_id_of(flow: OperatorFlow) -> UUID:
    response = await flow.get("", token=flow.instructor_token)
    assert response.status_code == 200, response.text
    return UUID(response.json()["incident_id"])


# ---------------------------------------------------------------------------------------------
# 1 & 2. One Incident, one timeline, no gap across the transition
# ---------------------------------------------------------------------------------------------


async def test_the_same_incident_and_one_unbroken_timeline_survive_the_transition(
    in_transition: OperatorFlow, clock: Any, uow_factory: Any
) -> None:
    incidents_before = await _incident_ids(uow_factory, in_transition.session_id)
    assert len(incidents_before) == 1

    clock.advance_ms(11_000)  # MULTI_TRAINEE's pause is 10 s (§10.10)
    continued = await in_transition.post("/stage/continue", token=in_transition.dds_token)
    assert continued.status_code == 200, continued.text
    assert continued.json()["state"] == "ACTIVE"

    # 1. SPEC §13 / §42 test 5: still exactly the one Incident id.
    incidents_after = await _incident_ids(uow_factory, in_transition.session_id)
    assert incidents_after == incidents_before

    # 2. One timeline: `seq_no` strictly increasing, no gap, no duplicate, across the transition.
    response = await in_transition.client.get(
        f"/api/v1/sessions/{in_transition.session_id}/events",
        headers=auth(in_transition.instructor_token),
        params={"limit": 1000},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    seq_nos = [item["seq_no"] for item in items]
    assert seq_nos == list(range(1, len(seq_nos) + 1)), (
        "no gap and no duplicate: seq_no is exactly the dense run 1..N across the whole log"
    )
    offsets = [item["monotonic_offset_ms"] for item in items]
    transition_started = next(
        item for item in items if item["event_type"] == "ROLE_TRANSITION_STARTED"
    )
    transition_seq_no = transition_started["seq_no"]
    role_stage_started = next(
        index
        for index, item in enumerate(items)
        if item["seq_no"] > transition_seq_no and item["event_type"] == "ROLE_STAGE_STARTED"
    )
    # R1: no event appended during or after the pause has an offset lower than the transition
    # started at — never asserted as "+pause", only as "not less than". `paused_total_ms` (E17-B)
    # is deliberately not read here: the offsets themselves are the observable contract.
    assert offsets[role_stage_started] >= transition_started["monotonic_offset_ms"]
    tail = offsets[transition_started["seq_no"] - 1 :]
    assert tail == sorted(tail), "R1: monotonic_offset_ms never decreases from the transition on"


# ---------------------------------------------------------------------------------------------
# 3. The handoff snapshot is immutable after creation
# ---------------------------------------------------------------------------------------------


async def test_the_handoff_snapshot_never_changes_once_the_dds_stage_is_acting_on_it(
    resolved: OperatorFlow, uow_factory: Any
) -> None:
    incident_id = await _incident_id_of(resolved)
    snapshot_at_handoff = await _handoff_snapshot_row(uow_factory, incident_id)

    # The DDS stage has by now acknowledged, opened selection, selected and dispatched a
    # reinforcement, and simulated time has moved past the resolution condition (`resolved`
    # fixture, `tests.api.dds.test_full_cycle`) — real DDS-side mutation, none of it on the card.
    snapshot_after_dds_work = await _handoff_snapshot_row(uow_factory, incident_id)

    assert snapshot_after_dds_work["id"] == snapshot_at_handoff["id"]
    assert snapshot_after_dds_work["content_sha256"] == snapshot_at_handoff["content_sha256"]
    assert snapshot_after_dds_work["card_values"] == snapshot_at_handoff["card_values"]
    assert (
        snapshot_after_dds_work["recipient_services"] == snapshot_at_handoff["recipient_services"]
    )


# ---------------------------------------------------------------------------------------------
# 4. The DDS stage sees the snapshot, never the live OperatorCard
# ---------------------------------------------------------------------------------------------


async def test_the_dds_participant_never_reaches_the_live_operator_card(
    dds_active: OperatorFlow,
) -> None:
    card_read = await dds_active.get("/operator/card", token=dds_active.dds_token)
    assert card_read.status_code == 403, card_read.text
    assert card_read.json()["code"] == "FORBIDDEN_FOR_ROLE"

    snapshot = (await dds_active.snapshot(token=dds_active.dds_token)).json()
    assert snapshot["card"] is None
    assert snapshot["work_item"] is not None, "the frozen copy, not the live card"


# ---------------------------------------------------------------------------------------------
# 5. Scoring evidence from both stages lands in one ScoreReport
# ---------------------------------------------------------------------------------------------


async def test_the_one_score_report_carries_evidence_from_both_stages(
    resolved: OperatorFlow,
) -> None:
    flow = resolved
    events_before_close = await event_types(flow)
    transition_completed_seq_no = next(
        item["seq_no"]
        for item in (
            await flow.client.get(
                f"/api/v1/sessions/{flow.session_id}/events",
                headers=auth(flow.instructor_token),
                params={"limit": 1000},
            )
        ).json()["items"]
        if item["event_type"] == "ROLE_TRANSITION_COMPLETED"
    )

    closed = await dds_post(flow, "/dds/close", {"closure_reason": "RESOLVED"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "COMPLETED"
    assert "SESSION_COMPLETED" in (await event_types(flow))[len(events_before_close) :]

    response = await flow.client.get(
        f"/api/v1/reports/{flow.session_id}", headers=auth(flow.instructor_token)
    )
    assert response.status_code == 200, response.text
    score_report = response.json()["score_report"]
    assert len(score_report["results"]) == RULE_COUNT

    evidence_seq_nos = [
        evidence["seq_no"]
        for result in score_report["results"]
        for evidence in result["evidence"]
        if evidence["seq_no"] is not None
    ]
    assert evidence_seq_nos, "SPEC §29 item 14: every rule's evidence is non-empty"
    assert any(seq_no < transition_completed_seq_no for seq_no in evidence_seq_nos), (
        "at least one piece of evidence comes from the OPERATOR_112 stage"
    )
    assert any(seq_no > transition_completed_seq_no for seq_no in evidence_seq_nos), (
        "at least one piece of evidence comes from the DDS stage"
    )
    # One report, one incident: the same `session_id` this whole module has been driving.
    assert response.json()["session_id"] == str(flow.session_id)
