"""Trainee groups, per-workstation cards and difficulty-weight proposals over HTTP (I3 E9a; HLD 70
§70.3.7; F-15).

* groups: CRUD for an instructor, refused to a trainee, members must be active trainees; a lesson
  "for a group" records `group_id` (unknown group → 404; deleting the group leaves the lesson and
  its participants, with `group_id = null`);
* the checkbox matrix end to end: a plan entry's `participants` decides whose card it is — each
  trainee's incident list and lesson detail show their own cards only, and another trainee's
  card session refuses them;
* weight proposals: requested proposals are stored and **never** change a weight; the gate's
  empty-script `FakeLLM` answers nothing parseable, so the heuristic answers (`fallback_reason`);
  a scripted LLM answer is the LLM's; accepting a subset writes exactly those weights; the report
  uses the accepted weights only, over unchanged card scores; creator-or-admin only.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.domain.common.ids import ScenarioVersionId
from app.inference.llm.fake_llm import FakeLLM

from tests.api.conftest import auth
from tests.api.lessons.conftest import Lessons, plan_entry
from tests.api.lessons.test_lessons import _complete_dds_card

pytestmark = pytest.mark.integration


def _dds(user_id: Any) -> dict[str, str]:
    return {"user_id": str(user_id), "assigned_role_type": "DDS"}


async def _group(lessons: Lessons, name: str, *members: str) -> dict[str, Any]:
    response = await lessons.client.post(
        "/api/v1/trainee-groups",
        headers=lessons.instructor,
        json={"name_ru": name, "member_user_ids": [str(lessons.users[m]) for m in members]},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------------------------


async def test_an_instructor_creates_reads_renames_and_deletes_a_group(lessons: Lessons) -> None:
    created = await _group(lessons, "Группа А", "trainee2", "trainee1")
    assert created["name_ru"] == "Группа А"
    assert created["created_by_user_id"] == str(lessons.users["instructor1"])
    assert [m["username"] for m in created["members"]] == ["trainee1", "trainee2"]
    assert created["members"][0]["display_name_ru"] == "Стажёр"
    group_id = created["group_id"]

    listed = await lessons.client.get("/api/v1/trainee-groups", headers=lessons.instructor)
    assert listed.status_code == 200, listed.text
    assert group_id in [item["group_id"] for item in listed.json()["items"]]

    renamed = await lessons.client.put(
        f"/api/v1/trainee-groups/{group_id}",
        headers=lessons.instructor,
        json={"name_ru": "Группа Б", "member_user_ids": [str(lessons.users["trainee1"])]},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name_ru"] == "Группа Б"
    assert [m["username"] for m in renamed.json()["members"]] == ["trainee1"]

    got = await lessons.client.get(
        f"/api/v1/trainee-groups/{group_id}", headers=auth(lessons.tokens["admin1"])
    )
    assert got.status_code == 200 and got.json() == renamed.json()

    deleted = await lessons.client.delete(
        f"/api/v1/trainee-groups/{group_id}", headers=lessons.instructor
    )
    assert deleted.status_code == 204
    gone = await lessons.client.get(
        f"/api/v1/trainee-groups/{group_id}", headers=lessons.instructor
    )
    assert gone.status_code == 404 and gone.json()["code"] == "NOT_FOUND"


async def test_groups_are_refused_to_a_trainee_and_take_active_trainees_only(
    lessons: Lessons,
) -> None:
    trainee = auth(lessons.tokens["trainee1"])
    listed = await lessons.client.get("/api/v1/trainee-groups", headers=trainee)
    assert listed.status_code == 403 and listed.json()["code"] == "FORBIDDEN_FOR_ROLE"
    created = await lessons.client.post(
        "/api/v1/trainee-groups", headers=trainee, json={"name_ru": "x", "member_user_ids": []}
    )
    assert created.status_code == 403

    for member in ("instructor1", "retired1"):
        refused = await lessons.client.post(
            "/api/v1/trainee-groups",
            headers=lessons.instructor,
            json={"name_ru": "Группа", "member_user_ids": [str(lessons.users[member])]},
        )
        assert refused.status_code == 422, (member, refused.text)
        assert refused.json()["code"] == "VALIDATION_ERROR"
    unknown = await lessons.client.post(
        "/api/v1/trainee-groups",
        headers=lessons.instructor,
        json={"name_ru": "Группа", "member_user_ids": [str(uuid4())]},
    )
    assert unknown.status_code == 422
    blank = await lessons.client.post(
        "/api/v1/trainee-groups", headers=lessons.instructor, json={"name_ru": "   "}
    )
    assert blank.status_code == 422
    missing = await lessons.client.put(
        f"/api/v1/trainee-groups/{uuid4()}",
        headers=lessons.instructor,
        json={"name_ru": "Группа", "member_user_ids": []},
    )
    assert missing.status_code == 404


async def test_a_lesson_for_a_group_records_it_and_outlives_the_group(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    group = await _group(lessons, "Смена 1", "trainee1", "trainee2")
    unknown = await lessons.create([plan_entry(1, demo_version_id)], group_id=str(uuid4()))
    assert unknown.status_code == 404 and unknown.json()["code"] == "NOT_FOUND"

    detail = await lessons.created(
        [plan_entry(1, demo_version_id)],
        participants=[_dds(lessons.users["trainee2"])],
        group_id=group["group_id"],
    )
    assert detail["group_id"] == group["group_id"]
    await lessons.client.delete(
        f"/api/v1/trainee-groups/{group['group_id']}", headers=lessons.instructor
    )
    after = await lessons.get(detail["lesson_id"])
    assert after["group_id"] is None
    assert after["participants"] == detail["participants"]
    assert [card["state"] for card in after["sessions"]] == ["READY"]


# ---------------------------------------------------------------------------------------------
# The checkbox matrix — PlanEntry.participants end to end
# ---------------------------------------------------------------------------------------------


async def test_each_trainee_sees_only_the_cards_ticked_for_their_workstation(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    trainee1, trainee2 = lessons.users["trainee1"], lessons.users["trainee2"]
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id, participants=[trainee1]),
            plan_entry(2, demo_version_id, participants=[trainee2]),
            plan_entry(3, demo_version_id, participants=[trainee2]),
        ],
        participants=[_dds(trainee1), _dds(trainee2)],
    )
    lesson_id = detail["lesson_id"]
    sessions = {card["position"]: card["session_id"] for card in detail["sessions"]}
    await lessons.start(lesson_id)
    assert await lessons.states(lesson_id) == ["ACTIVE", "ACTIVE", "ACTIVE"]

    async def incident_sessions(username: str) -> list[str]:
        response = await lessons.client.get(
            "/api/v1/incidents",
            headers=auth(lessons.tokens[username]),
            params={"lesson_id": lesson_id},
        )
        assert response.status_code == 200, response.text
        return sorted(row["session_id"] for row in response.json()["items"])

    assert await incident_sessions("trainee1") == [sessions[1]]
    assert await incident_sessions("trainee2") == sorted([sessions[2], sessions[3]])

    mine = await lessons.get(lesson_id, lessons.tokens["trainee1"])
    assert [card["position"] for card in mine["sessions"]] == [1]
    everything = await lessons.get(lesson_id)
    assert [card["position"] for card in everything["sessions"]] == [1, 2, 3]

    # Each card's session has exactly the ticked participant: the other trainee is refused.
    foreign = await lessons.client.get(
        f"/api/v1/sessions/{sessions[2]}/dds/work-item", headers=auth(lessons.tokens["trainee1"])
    )
    assert foreign.status_code == 403, foreign.text


# ---------------------------------------------------------------------------------------------
# Weight proposals
# ---------------------------------------------------------------------------------------------


async def _two_card_lesson(lessons: Lessons, version_id: ScenarioVersionId) -> dict[str, Any]:
    return await lessons.created(
        [
            plan_entry(1, version_id),
            plan_entry(2, version_id, offset_ms=10**9),
        ]
    )


async def test_proposals_are_stored_and_never_change_a_weight_before_accept(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await _two_card_lesson(lessons, demo_version_id)
    lesson_id = detail["lesson_id"]
    base = f"/api/v1/lessons/{lesson_id}/weight-proposals"
    before = await lessons.client.get(base, headers=lessons.instructor)
    assert before.status_code == 404 and before.json()["code"] == "NOT_FOUND"

    requested = await lessons.client.post(base, headers=lessons.instructor)
    assert requested.status_code == 201, requested.text
    body = requested.json()
    assert body["source"] == "HEURISTIC", "the gate's empty FakeLLM answers nothing parseable"
    assert body["fallback_reason"] == "LLM_INVALID_OUTPUT"
    assert [line["position"] for line in body["proposals"]] == [1, 2]
    assert all(1 <= line["proposed_weight"] <= 10 for line in body["proposals"])
    assert all(line["reason_ru"] for line in body["proposals"])
    assert [line["current_weight"] for line in body["proposals"]] == [1.0, 1.0]
    assert [line["accepted_at"] for line in body["proposals"]] == [None, None]

    plan = (await lessons.get(lesson_id))["scenario_plan"]
    assert [entry["weight"] for entry in plan] == [1.0, 1.0], "a proposal is not a weight"
    got = await lessons.client.get(base, headers=lessons.instructor)
    assert got.status_code == 200 and got.json() == body


async def test_a_scripted_llm_answer_is_stored_as_the_llms(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await _two_card_lesson(lessons, demo_version_id)
    llm = FakeLLM(
        [
            {
                "proposals": [
                    {"position": 1, "weight": 7, "reason_ru": "Пожар в жилом доме"},
                    {"position": 2, "weight": 4, "reason_ru": "Повтор"},
                ]
            }
        ]
    )
    lessons.container._explanation_llm_client = llm  # type: ignore[attr-defined]
    response = await lessons.client.post(
        f"/api/v1/lessons/{detail['lesson_id']}/weight-proposals", headers=lessons.instructor
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["source"], body["model_name"], body["fallback_reason"]) == (
        "LLM",
        "fake-llm",
        None,
    )
    assert [line["proposed_weight"] for line in body["proposals"]] == [7, 4]
    [call] = llm.calls
    prompt = "\n".join(message.content for message in call.messages)
    assert "сложность" in prompt and "Карточка 2" in prompt


async def test_accept_writes_the_chosen_weights_and_the_report_uses_them_only(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await lessons.created(
        [
            plan_entry(1, demo_version_id),
            plan_entry(2, demo_version_id, offset_ms=10**9),
            plan_entry(3, demo_version_id, offset_ms=10**9),
        ]
    )
    lesson_id = detail["lesson_id"]
    await lessons.start(lesson_id)
    await _complete_dds_card(lessons, detail["sessions"][0]["session_id"])
    for card in detail["sessions"][1:]:
        await lessons.client.post(
            f"/api/v1/sessions/{card['session_id']}/abort",
            headers=lessons.instructor,
            json={"reason": "x"},
        )
    assert (await lessons.tick(lesson_id)).completed
    report_url = f"/api/v1/lessons/{lesson_id}/report"
    original = (await lessons.client.get(report_url, headers=lessons.instructor)).json()
    [card] = original["cards"]
    assert card["weight"] == 1.0

    base = f"/api/v1/lessons/{lesson_id}/weight-proposals"
    proposed = (await lessons.client.post(base, headers=lessons.instructor)).json()
    unchanged = (await lessons.client.get(report_url, headers=lessons.instructor)).json()
    assert unchanged == original, "requesting proposals rescores and reweights nothing"

    weights = {line["position"]: line["proposed_weight"] for line in proposed["proposals"]}
    accepted = await lessons.client.post(
        f"{base}/accept", headers=lessons.instructor, json={"positions": [1, 3]}
    )
    assert accepted.status_code == 200, accepted.text
    lines = {line["position"]: line for line in accepted.json()["proposals"]}
    assert lines[1]["current_weight"] == weights[1] and lines[1]["accepted_at"] is not None
    assert lines[2]["current_weight"] == 1.0 and lines[2]["accepted_at"] is None
    assert lines[3]["current_weight"] == weights[3]
    plan = (await lessons.get(lesson_id))["scenario_plan"]
    assert [entry["weight"] for entry in plan] == [weights[1], 1.0, weights[3]]

    report = (await lessons.client.get(report_url, headers=lessons.instructor)).json()
    [reweighted] = report["cards"]
    assert reweighted["score"] == card["score"], "the card's own score is untouched"
    assert reweighted["weight"] == weights[1]
    assert report["weighted_total"] == pytest.approx(weights[1] * card["score"]["total_points"])
    assert report["weighted_max"] == pytest.approx(weights[1] * card["score"]["total_max_points"])


async def test_proposals_are_the_creators_or_an_admins_and_accept_checks_positions(
    lessons: Lessons, demo_version_id: ScenarioVersionId
) -> None:
    detail = await _two_card_lesson(lessons, demo_version_id)
    base = f"/api/v1/lessons/{detail['lesson_id']}/weight-proposals"
    trainee = await lessons.client.post(base, headers=auth(lessons.tokens["trainee2"]))
    assert trainee.status_code == 403
    no_proposals = await lessons.client.post(
        f"{base}/accept", headers=lessons.instructor, json={"positions": [1]}
    )
    assert no_proposals.status_code == 404
    admin = await lessons.client.post(base, headers=auth(lessons.tokens["admin1"]))
    assert admin.status_code == 201, admin.text
    unknown = await lessons.client.post(
        f"{base}/accept", headers=lessons.instructor, json={"positions": [5]}
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "VALIDATION_ERROR"
    empty = await lessons.client.post(
        f"{base}/accept", headers=lessons.instructor, json={"positions": []}
    )
    assert empty.status_code == 422
    missing = await lessons.client.post(
        f"/api/v1/lessons/{uuid4()}/weight-proposals", headers=lessons.instructor
    )
    assert missing.status_code == 404
