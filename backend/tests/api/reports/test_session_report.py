"""`getSessionReport` end to end: every SPEC §29 item, over real HTTP and a real database.

The report is the epic's whole point, so the happy-path test is deliberately exhaustive: it
drives the committed demo scenario through 112 -> handoff -> DDS -> closure and then asserts that
**each of the fourteen items** is present and non-empty for the instructor. A report that renders
an empty timeline or a `null` handoff would otherwise pass a shape check and fail a human.

The rest pin the refusals (R1), the release gate (R2/R3), the per-viewer filtering (R3) and the
property the whole design rests on: **reading a report writes nothing** — same score rows, same
checksum, no new events, and `rescoreSession` afterwards still `identical_to_stored`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.domain.common.ids import SessionId

from tests.api.conftest import auth, create_demo_session, participant
from tests.api.reports.conftest import OperatorFlow, dds_post, release, report

pytestmark = pytest.mark.integration

RULE_COUNT = 10
"""The demo scenario's own `scoring_rules` count (`scenarios/examples/apartment-fire/v1.yaml`)."""


async def _counts(uow_factory: Any, session_id: Any) -> tuple[int, int]:
    """`(score_results rows, session_events rows)` — the two things a read must not move."""
    async with uow_factory() as uow:
        scores = await uow.session.execute(
            sa.text("SELECT count(*) FROM score_results WHERE session_id = :s"),
            {"s": session_id},
        )
        events = await uow.session.execute(
            sa.text("SELECT count(*) FROM session_events WHERE session_id = :s"),
            {"s": session_id},
        )
        result = (int(scores.scalar_one()), int(events.scalar_one()))
        await uow.commit()
    return result


# ---------------------------------------------------------------------------------------------
# The happy path: all fourteen SPEC §29 items
# ---------------------------------------------------------------------------------------------


async def test_the_instructor_report_has_every_spec_29_item(completed: OperatorFlow) -> None:
    """SPEC §29 items 1-14, each asserted by name and by content."""
    response = await report(completed)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["session_id"] == str(completed.session_id)
    assert body["session"]["state"] == "COMPLETED"

    # 1 total score, 2 by category, 3 critical errors, 14 evidence per rule
    score = body["score_report"]
    assert score["total_max_points"] > 0
    assert len(score["results"]) == RULE_COUNT
    assert score["by_category"], "SPEC §29 item 2"
    assert isinstance(score["critical_errors"], list), "SPEC §29 item 3"
    assert score["checksum"]
    for result in score["results"]:
        assert result["evidence"], f"SPEC §29 item 14: rule {result['rule_id']} has no evidence"
        assert result["name_ru"] and result["description_ru"]

    # 4 complete event timeline, with a Russian one-line summary each
    timeline = body["timeline"]
    assert len(timeline) > 20, "SPEC §29 item 4: the whole cycle, not a sample"
    assert [entry["seq_no"] for entry in timeline] == sorted(entry["seq_no"] for entry in timeline)
    assert all(entry["summary_ru"] for entry in timeline)
    assert {entry["event_type"] for entry in timeline} >= {
        "SESSION_STARTED",
        "HANDOFF_CREATED",
        "DDS_ACKNOWLEDGED",
        "RESOURCE_DISPATCHED",
        "SCORING_RULE_EVALUATED",
        "SESSION_COMPLETED",
    }

    # 5 transcript, 6 audio references, 7 click-to-seek offsets
    assert body["transcript"], "SPEC §29 item 5"
    for segment in body["transcript"]:
        assert segment["speaker"] in {"OPERATOR", "CALLER"}, "E16 R5: the contract's enum"
        assert isinstance(segment["start_ms"], int), "SPEC §29 item 7: the seek target"
    assert isinstance(body["audio_segments"], list), "SPEC §29 item 6"

    # 8 the final card
    assert body["final_card"]["values"], "SPEC §29 item 8"
    assert body["final_card"]["field_specs"]

    # 9 the truth-vs-card diff — the one place WorldTruth reaches a human (D11)
    diff = body["truth_vs_card_diff"]
    assert diff, "SPEC §29 item 9"
    assert {entry["verdict"] for entry in diff} <= {
        "MATCH",
        "MISMATCH",
        "MISSING",
        "NOT_COMPARABLE",
    }
    assert all(entry["label_ru"] for entry in diff)

    # 10 the handoff snapshot
    assert body["handoff"] is not None, "SPEC §29 item 10"
    assert body["handoff"]["recipient_services"]
    assert body["handoff"]["content_sha256"]

    # 11 DDS decisions, 12 resource timeline
    decisions = body["dds_decisions"]
    assert decisions, "SPEC §29 item 11"
    assert any(decision["dispatch_events"] for decision in decisions)
    assert any(decision["closure_reason"] == "RESOLVED" for decision in decisions)
    resource_steps = body["resource_timeline"]
    assert resource_steps, "SPEC §29 item 12"
    assert {step["new_status"] for step in resource_steps} >= {"DISPATCHED"}
    assert all(step["callsign"] for step in resource_steps)

    # 13 timing metrics — measured or null, never faked (SPEC §27)
    timing = body["timing_metrics"]
    assert set(timing) == {
        "turn_count",
        "speech_end_to_first_audio_ms_p50",
        "speech_end_to_first_audio_ms_p95",
        "asr_latency_ms_p50",
        "llm_ttft_ms_p50",
        "tts_first_audio_ms_p50",
        "barge_in_cutoff_ms_p95",
        "fallback_count",
    }
    assert isinstance(timing["turn_count"], int)

    assert body["explanation_available"] is False
    assert body["released"] is False


async def test_computed_from_event_count_is_the_true_count_not_a_placeholder(
    completed: OperatorFlow, uow_factory: Any
) -> None:
    """I3 E0 D8: the loaded-report path must show the same figure `score()` itself derived at
    scoring time (`ScoringContext.computed_from_event_count`), never a hard-coded 0 — the label
    ("Событий учтено") and the number it names must agree.

    `SCORING_RULE_EVALUATED` (`RULE_COUNT` rows, one per scoring rule) is the only event type
    `score()` itself produces and therefore excludes from its own count (`context.py`'s
    `_SCORING_EVENT_TYPES`); every other `session_events` row for this session is counted.
    """
    response = await report(completed)
    assert response.status_code == 200, response.text
    computed = response.json()["score_report"]["computed_from_event_count"]
    assert computed > 0

    _, session_events_count = await _counts(uow_factory, completed.session_id)
    assert computed == session_events_count - RULE_COUNT


# ---------------------------------------------------------------------------------------------
# R1 — the refusals
# ---------------------------------------------------------------------------------------------


async def test_a_report_for_an_unfinished_session_is_refused(dds_active: OperatorFlow) -> None:
    """The epic's own invariant: the session is `ACTIVE`, so there is nothing to report."""
    response = await report(dds_active)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPORT_NOT_READY"


async def test_a_report_for_an_aborted_session_is_refused(dds_active: OperatorFlow) -> None:
    """An `ABORTED` session is never scored (R1), so it has no report either."""
    aborted = await dds_active.client.post(
        f"/api/v1/sessions/{dds_active.session_id}/abort",
        headers=auth(dds_active.instructor_token),
        json={"reason": "учебная остановка"},
    )
    assert aborted.status_code == 200, aborted.text

    response = await report(dds_active)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPORT_NOT_READY"


async def test_an_unknown_session_is_a_404(completed: OperatorFlow) -> None:
    response = await completed.client.get(
        "/api/v1/reports/00000000-0000-4000-8000-0000000000ff",
        headers=auth(completed.instructor_token),
    )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------------------------
# R2/R3 — release and per-viewer visibility
# ---------------------------------------------------------------------------------------------


async def test_a_trainee_is_refused_before_release_in_a_gated_mode(
    completed: OperatorFlow,
) -> None:
    """The chain runs `MULTI_TRAINEE`, whose `report_visible_to_trainee_before_release` is false
    (D6 §10.10)."""
    response = await report(completed, token=completed.operator_token)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "REPORT_NOT_RELEASED"


async def test_release_opens_the_report_to_the_trainee(completed: OperatorFlow) -> None:
    released = await release(completed)
    assert released.status_code == 200, released.text
    body = released.json()
    assert body["released"] is True
    assert body["released_at"] is not None
    assert body["released_by_user_id"] is not None

    response = await report(completed, token=completed.operator_token)
    assert response.status_code == 200, response.text
    assert response.json()["released"] is True


async def test_release_is_idempotent(completed: OperatorFlow) -> None:
    """A second call returns the first release unchanged — same instant, same author (R2)."""
    first = (await release(completed)).json()
    second = (await release(completed)).json()
    assert second == first


async def test_release_emits_no_event(completed: OperatorFlow, uow_factory: Any) -> None:
    """`x-emits: []`. Appending to a completed session's log would change the very input
    `rescoreSession` replays (SPEC §28, D5)."""
    before = await _counts(uow_factory, completed.session_id)
    assert (await release(completed)).status_code == 200
    assert await _counts(uow_factory, completed.session_id) == before


async def test_a_trainee_may_not_release(completed: OperatorFlow) -> None:
    response = await release(completed, token=completed.operator_token)
    assert response.status_code == 403, response.text


async def test_releasing_an_unfinished_session_is_refused(dds_active: OperatorFlow) -> None:
    response = await release(dds_active)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "REPORT_NOT_READY"


async def test_the_operator_trainee_sees_the_call_but_not_the_dds_decisions(
    completed: OperatorFlow,
) -> None:
    """R3's table, over the wire: the sections are **empty**, never omitted."""
    assert (await release(completed)).status_code == 200
    body = (await report(completed, token=completed.operator_token)).json()

    assert body["transcript"], "their own call"
    assert body["final_card"]["values"], "their own card"
    assert body["truth_vs_card_diff"], "their own diff"
    assert body["handoff"] is not None, "the hand-over they made"
    assert body["dds_decisions"] == [], "what the DDS then did is not theirs to read"
    assert body["resource_timeline"] == []
    assert "dds_decisions" in body and "resource_timeline" in body, "empty, never omitted"


async def test_the_dds_trainee_sees_the_decisions_but_not_the_call(
    completed: OperatorFlow,
) -> None:
    assert (await release(completed)).status_code == 200
    body = (await report(completed, token=completed.dds_token)).json()

    assert body["dds_decisions"], "their own decisions"
    assert body["resource_timeline"], "their own units"
    assert body["handoff"] is not None, "the hand-over they received"
    assert body["transcript"] == [], "the caller's voice is the operator stage's"
    assert body["audio_segments"] == []
    assert body["truth_vs_card_diff"] == [], "D11's exception is the operator card's"
    assert body["final_card"]["values"] == {}, "emptied, not omitted (R3)"


async def test_the_totals_are_the_whole_session_s_for_every_viewer(
    completed: OperatorFlow,
) -> None:
    """One report, one checksum (R3, D11): numbers are never re-aggregated per viewer."""
    assert (await release(completed)).status_code == 200
    instructor = (await report(completed)).json()["score_report"]
    operator = (await report(completed, token=completed.operator_token)).json()["score_report"]
    dds = (await report(completed, token=completed.dds_token)).json()["score_report"]

    for view in (operator, dds):
        assert view["total_points"] == instructor["total_points"]
        assert view["total_max_points"] == instructor["total_max_points"]
        assert view["checksum"] == instructor["checksum"]


async def test_a_non_participant_trainee_may_not_read_the_report(
    client: Any, tokens: Any, users: Any, demo_version_id: Any
) -> None:
    """A trainee reads only a session they participated in (R3).

    The check runs *before* the `COMPLETED` one on purpose: a stranger must not be able to tell
    an unfinished session from a finished one by the status code they get back.
    """
    session = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], None)],
        session_mode="FULL_CYCLE_SINGLE_TRAINEE",
    )
    response = await client.get(
        f"/api/v1/reports/{session['id']}", headers=auth(tokens["trainee2"])
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PARTICIPANT_NOT_ASSIGNED"


# ---------------------------------------------------------------------------------------------
# The report writes nothing
# ---------------------------------------------------------------------------------------------


async def test_reading_the_report_writes_nothing(completed: OperatorFlow, uow_factory: Any) -> None:
    """R1, asserted rather than asserted-in-a-docstring: the score rows, the checksum and the
    event count are all unchanged, and a rescore afterwards is still identical."""
    before_counts = await _counts(uow_factory, completed.session_id)
    before_checksum = (await report(completed)).json()["score_report"]["checksum"]

    for _ in range(3):
        assert (await report(completed)).status_code == 200

    assert await _counts(uow_factory, completed.session_id) == before_counts
    assert (await report(completed)).json()["score_report"]["checksum"] == before_checksum

    rescore = await completed.client.post(
        f"/api/v1/reports/{completed.session_id}/rescore",
        headers=auth(completed.instructor_token),
        json={"persist": False},
    )
    assert rescore.status_code == 200, rescore.text
    outcome = rescore.json()
    assert outcome["identical_to_stored"] is True
    assert outcome["stored_checksum"] == before_checksum


async def test_the_report_checksum_is_the_stored_one(completed: OperatorFlow) -> None:
    """The report *reads* the score; `rescoreSession` recomputes it. The two must agree, and the
    report's `checksum` is by construction the stored one (R1, §10.14 reading #10)."""
    body = (await report(completed)).json()
    rescore = await completed.client.post(
        f"/api/v1/reports/{completed.session_id}/rescore",
        headers=auth(completed.instructor_token),
        json={"persist": False},
    )
    assert body["score_report"]["checksum"] == rescore.json()["stored_checksum"]


# ---------------------------------------------------------------------------------------------
# listInferenceMetrics (SPEC §27)
# ---------------------------------------------------------------------------------------------


async def test_the_metrics_page_shares_the_report_s_timing_block(
    completed: OperatorFlow,
) -> None:
    """One aggregator, two callers (R6): the numbers must be the same object's output."""
    page = await completed.client.get(
        f"/api/v1/reports/{completed.session_id}/inference-metrics",
        headers=auth(completed.instructor_token),
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert isinstance(body["items"], list)
    assert body["total"] == len(body["items"]) or body["total"] >= len(body["items"])
    assert body["timing_metrics"] == (await report(completed)).json()["timing_metrics"]


async def test_speech_end_to_first_audio_percentiles_are_present_over_three_turns(
    completed: OperatorFlow, uow_factory: Any
) -> None:
    """H3 (E20-H): the report reads the *stored* `dialogue_turns.speech_end_to_first_audio_ms`
    column (E16's stored-only rule, no recomputation from events) — SPEC §27's own metric, so it
    must not silently stay `null` when the column has rows to aggregate.

    `completed` already seeds turn 0 at 880 ms (`tests.api.reports.conftest._seed_voice_artefacts`);
    this adds two more turns directly through the port, exactly as E12/E14 would in production, and
    checks the nearest-rank percentiles of the three (`app.application.reports.timing_metrics
    .percentile`: p50 of `[880, 1200, 2000]` is the 2nd value, p95 is the 3rd).
    """
    session_id = SessionId(completed.session_id)
    async with uow_factory() as uow:
        stage_id = (await uow.sessions.get(session_id)).stages[0].role_stage_id
        for turn_index, value in ((1, 1200), (2, 2000)):
            await uow.dialogue_turns.upsert(
                DialogueTurnUpsert(
                    id=uuid4(),
                    session_id=session_id,
                    role_stage_id=stage_id,
                    turn_index=turn_index,
                    user_speech_started_offset_ms=3000 + turn_index * 1000,
                )
            )
            await uow.dialogue_turns.set_speech_end_to_first_audio_ms(session_id, turn_index, value)
        await uow.commit()

    body = (await report(completed)).json()
    timing = body["timing_metrics"]
    assert timing["turn_count"] == 3
    assert timing["speech_end_to_first_audio_ms_p50"] == 1200.0
    assert timing["speech_end_to_first_audio_ms_p95"] == 2000.0


async def test_the_component_filter_does_not_move_the_aggregate(
    completed: OperatorFlow,
) -> None:
    """`timing_metrics` is the whole session's; a p50 that moved with the reader's filter would
    be a different metric with the same name (SPEC §27)."""
    unfiltered = (
        await completed.client.get(
            f"/api/v1/reports/{completed.session_id}/inference-metrics",
            headers=auth(completed.instructor_token),
        )
    ).json()
    filtered = (
        await completed.client.get(
            f"/api/v1/reports/{completed.session_id}/inference-metrics",
            headers=auth(completed.instructor_token),
            params={"component": "ASR"},
        )
    ).json()
    assert filtered["timing_metrics"] == unfiltered["timing_metrics"]
    assert all(item["component"] == "ASR" for item in filtered["items"])


async def test_the_limit_is_bounded_by_the_contract(completed: OperatorFlow) -> None:
    response = await completed.client.get(
        f"/api/v1/reports/{completed.session_id}/inference-metrics",
        headers=auth(completed.instructor_token),
        params={"limit": 9999},
    )
    assert response.status_code == 422, response.text


async def test_closing_still_scores_the_session(completed: OperatorFlow) -> None:
    """A baseline the whole file depends on: the close scored the session (E15-B)."""
    response = await dds_post(completed, "/dds/close", {"closure_reason": "RESOLVED"})
    assert response.status_code in {409, 200}, response.text
    assert (await report(completed)).json()["score_report"]["results"]
