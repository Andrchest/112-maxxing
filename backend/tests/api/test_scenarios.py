"""The six scenario endpoints, through HTTP (D3, D4, `openapi.yaml`)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import yaml
from app.domain.common.ids import ScenarioVersionId, UserId
from app.domain.scenario.validation import VALIDATION_RULE_NUMBERS

from tests.api.conftest import auth, create_demo_session, participant

pytestmark = pytest.mark.integration


async def test_list_scenarios_returns_identity_only(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """`listScenarios` gives slug, title and the version aggregates — never content (D4).

    It counts the whole catalog, so `isolated_scenario_catalog` (before `demo_version_id`, which
    then re-imports the demo into the emptied table) makes it independent of any other test that
    imported a scenario of its own into the session-shared `scenarios` table."""
    response = await client.get("/api/v1/scenarios", headers=auth(tokens["trainee1"]))

    assert response.status_code == 200
    body = response.json()
    # the demo and the schema-2 example `street-rubbish-fire` (I3 E3a), both from
    # `scenarios/examples`
    assert body["total"] == 2
    item = next(entry for entry in body["items"] if entry["slug"] == "apartment-fire")
    assert item["version_count"] == 1
    assert item["latest_version"] == 1
    assert set(item) == {
        "scenario_id",
        "slug",
        "title_ru",
        "version_count",
        "latest_version",
        "latest_difficulty",
        "archived_at",  # additive, I4 E32
        "category",  # additive, I7 E53
    }
    assert item["archived_at"] is None
    # I7 E53 (G13): the schema-1 demo names no incident code or type — «без категории»; the
    # schema-2 example's prefab card ticks «101» (`incident.types: ["1"]`) — group 1.
    assert item["category"] is None
    rubbish = next(entry for entry in body["items"] if entry["slug"] == "street-rubbish-fire")
    assert rubbish["category"] == {"group_no": 1, "name_ru": "Пожары и задымления"}


async def test_list_scenario_versions(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """`listScenarioVersions` lists the versions with `locked_at` still null (D4).

    `isolated_scenario_catalog` (which must run before `demo_version_id` re-imports into the now-
    empty catalog) is required here: the shared demo scenario is reused by session-creating tests
    across the whole suite and gets locked as soon as any of them runs, so only a freshly imported,
    nobody-else-has-touched-it copy can honestly assert `locked_at is None`.
    """
    scenarios = await client.get("/api/v1/scenarios", headers=auth(tokens["trainee1"]))
    scenario_id = scenarios.json()["items"][0]["scenario_id"]

    response = await client.get(
        f"/api/v1/scenarios/{scenario_id}/versions", headers=auth(tokens["trainee1"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["version"] == 1
    assert item["locked_at"] is None
    assert item["role_chain"] == ["OPERATOR_112", "DDS"]
    assert "content" not in item


async def test_list_versions_of_an_unknown_scenario_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """A scenario that does not exist is `404 NOT_FOUND`, as problem+json."""
    response = await client.get(
        "/api/v1/scenarios/00000000-0000-4000-8000-000000000000/versions",
        headers=auth(tokens["trainee1"]),
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "NOT_FOUND"


async def test_version_summary_is_trainee_safe(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_version_id: ScenarioVersionId
) -> None:
    """`getScenarioVersionSummary` leaks nothing a briefing would not say (D3, SPEC §2).

    The assertion is on the *whole payload text*, not on a field list: a value that leaked from
    `world_truth` would show up as a substring even under a field name nobody predicted.
    """
    response = await client.get(
        f"/api/v1/scenarios/versions/{demo_version_id}/summary",
        headers=auth(tokens["trainee1"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_slug"] == "apartment-fire"
    assert body["role_chain"] == ["OPERATOR_112", "DDS"]
    assert body["resource_count"] > 0
    assert body["estimated_duration_seconds"] is None
    forbidden = {
        "world_truth",
        "caller_knowledge",
        "disclosure_rules",
        "expected_response",
        "world_events",
        "scoring_rules",
        "available_resources",
        "deterministic_seed",
    }
    assert forbidden.isdisjoint(set(body))
    serialised = response.text
    for key in forbidden:
        assert key not in serialised


async def test_validation_report_is_instructor_only(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_version_id: ScenarioVersionId
) -> None:
    """`getScenarioValidationReport` is gated; the instructor sees a valid, complete report."""
    refused = await client.get(
        f"/api/v1/scenarios/versions/{demo_version_id}/validation-report",
        headers=auth(tokens["trainee1"]),
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"

    allowed = await client.get(
        f"/api/v1/scenarios/versions/{demo_version_id}/validation-report",
        headers=auth(tokens["instructor1"]),
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["valid"] is True
    assert body["checked_rule_count"] == len(VALIDATION_RULE_NUMBERS)
    assert body["scenario_slug"] == "apartment-fire"
    assert [issue for issue in body["issues"] if issue["severity"] == "ERROR"] == []


async def test_import_is_idempotent(
    client: httpx.AsyncClient, tokens: dict[str, str], demo_yaml: str
) -> None:
    """The same document twice answers `201` twice and creates exactly one version."""
    first = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "YAML", "content": demo_yaml, "source_path": "x/apartment-fire/v1.yaml"},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "YAML", "content": demo_yaml, "source_path": "x/apartment-fire/v1.yaml"},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["content_sha256"] == first.json()["content_sha256"]

    listed = await client.get("/api/v1/scenarios", headers=auth(tokens["instructor1"]))
    assert listed.json()["items"][0]["version_count"] == 1


async def test_changed_content_under_the_same_version_is_409(
    isolated_scenario_catalog: None,
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    demo_yaml: str,
) -> None:
    """Changed content at an existing version number is `409 SCENARIO_VERSION_EXISTS` (D4).

    `isolated_scenario_catalog`: the shared demo version is locked as soon as any earlier test on
    the same worker creates a session on it, and a changed import under a *locked* version is
    `SCENARIO_VERSION_LOCKED` instead — so this test imports its own, never-locked copy (I3 E8).
    """
    await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "YAML", "content": demo_yaml, "source_path": "x/apartment-fire/v1.yaml"},
    )

    mutated = yaml.safe_load(demo_yaml)
    mutated["description"] = mutated["description"] + " (edited)"
    response = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={
            "format": "JSON",
            "content": _json(mutated),
            "source_path": "x/apartment-fire/v1.yaml",
        },
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "SCENARIO_VERSION_EXISTS"


async def test_importing_a_broken_document_is_422_with_every_violation(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    demo_yaml: str,
    isolated_scenario_catalog: None,
) -> None:
    """A document that breaks several §30.8 rules answers `422 SCENARIO_INVALID` with all of them.

    `openapi.yaml`: "The problem carries the complete `validation_report`; nothing was written."
    `isolated_scenario_catalog`: the closing assertion needs the catalog to hold *nothing*, and the
    demo scenario is shared session-wide for speed (see `demo_version_id`).
    """
    broken = yaml.safe_load(demo_yaml)
    # Two independent violations, so "every violation" is a testable claim and not a tautology:
    # an unimplemented role in the chain (R18) and a caller fact that world truth does not define.
    broken["role_chain"] = ["EDDS"]
    broken["caller_knowledge"]["facts"]["invented_fact"] = {
        "caller_value": "x",
        "knowledge": "KNOWN",
        "certainty": 1.0,
    }

    response = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "JSON", "content": _json(broken)},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "SCENARIO_INVALID"
    report = body["validation_report"]
    assert report["valid"] is False
    assert report["checked_rule_count"] == len(VALIDATION_RULE_NUMBERS)
    rules = {issue["rule_number"] for issue in report["issues"] if issue["severity"] == "ERROR"}
    assert len(rules) >= 2, report["issues"]

    listed = await client.get("/api/v1/scenarios", headers=auth(tokens["instructor1"]))
    assert listed.json()["total"] == 0, "a rejected import must write nothing"


async def test_validate_always_answers_200(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    demo_yaml: str,
    isolated_scenario_catalog: None,
) -> None:
    """`validateScenarioFile` reports an invalid document in the body, not as an error status.

    `openapi.yaml`: "Always `200`: an invalid document is reported in the body as `valid: false`
    plus issues, because this endpoint's purpose is authoring feedback, not command execution."
    `isolated_scenario_catalog`: the closing assertion needs the catalog to hold nothing (see
    `test_importing_a_broken_document_is_422_with_every_violation`).
    """
    good = await client.post(
        "/api/v1/scenarios/validate",
        headers=auth(tokens["instructor1"]),
        json={"format": "YAML", "content": demo_yaml},
    )
    assert good.status_code == 200
    assert good.json()["valid"] is True

    broken = yaml.safe_load(demo_yaml)
    broken["role_chain"] = ["EDDS"]
    bad = await client.post(
        "/api/v1/scenarios/validate",
        headers=auth(tokens["instructor1"]),
        json={"format": "JSON", "content": _json(broken)},
    )
    assert bad.status_code == 200
    body = bad.json()
    assert body["valid"] is False
    assert body["issues"]

    listed = await client.get("/api/v1/scenarios", headers=auth(tokens["instructor1"]))
    assert listed.json()["total"] == 0, "validate writes nothing"


async def test_validate_of_an_unparseable_document_is_422(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    """A body that is not a document at all cannot be reported *in* a report."""
    response = await client.post(
        "/api/v1/scenarios/validate",
        headers=auth(tokens["instructor1"]),
        json={"format": "JSON", "content": "{not json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "SCENARIO_INVALID"


async def test_a_malformed_request_body_is_problem_json_422(
    client: httpx.AsyncClient, tokens: dict[str, str], users: dict[str, UserId]
) -> None:
    """FastAPI's own validation error is rendered as problem+json `VALIDATION_ERROR` too."""
    response = await client.post(
        "/api/v1/scenarios/import",
        headers=auth(tokens["instructor1"]),
        json={"format": "XML", "content": "irrelevant"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "VALIDATION_ERROR"


def _json(document: Any) -> str:
    import json

    return json.dumps(document, ensure_ascii=False)


# ---------------------------------------------------------------------------------------------
# I4 E32: archiveScenario / unarchiveScenario (`71-i4-wave4.md` §71.9, ТЗ ¶229)
# ---------------------------------------------------------------------------------------------


async def _scenario_id_of(
    client: httpx.AsyncClient, tokens: dict[str, str], scenario_version_id: ScenarioVersionId
) -> str:
    response = await client.get(
        f"/api/v1/scenarios/versions/{scenario_version_id}/summary",
        headers=auth(tokens["trainee1"]),
    )
    assert response.status_code == 200, response.text
    scenario_id: str = response.json()["scenario_id"]
    return scenario_id


async def test_archive_hides_scenario_from_listing_by_default(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """Archived is hidden from `listScenarios` unless `include_archived=true` (ТЗ ¶229)."""
    scenario_id = await _scenario_id_of(client, tokens, demo_version_id)

    before = await client.get("/api/v1/scenarios", headers=auth(tokens["trainee1"]))
    total_before = before.json()["total"]

    archived = await client.post(
        f"/api/v1/scenarios/{scenario_id}/archive", headers=auth(tokens["instructor1"])
    )
    assert archived.status_code == 200, archived.text
    body = archived.json()
    assert body["scenario_id"] == scenario_id
    assert body["archived_at"] is not None

    default_listing = await client.get("/api/v1/scenarios", headers=auth(tokens["trainee1"]))
    assert default_listing.json()["total"] == total_before - 1
    assert not any(item["scenario_id"] == scenario_id for item in default_listing.json()["items"])

    with_archived = await client.get(
        "/api/v1/scenarios", params={"include_archived": "true"}, headers=auth(tokens["trainee1"])
    )
    assert with_archived.json()["total"] == total_before
    item = next(i for i in with_archived.json()["items"] if i["scenario_id"] == scenario_id)
    assert item["archived_at"] is not None

    unarchived = await client.post(
        f"/api/v1/scenarios/{scenario_id}/unarchive", headers=auth(tokens["instructor1"])
    )
    assert unarchived.status_code == 200, unarchived.text
    assert unarchived.json()["archived_at"] is None

    restored_listing = await client.get("/api/v1/scenarios", headers=auth(tokens["trainee1"]))
    assert restored_listing.json()["total"] == total_before


async def test_archive_is_idempotent(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """A second `archiveScenario` call leaves the scenario archived (no error, no change)."""
    scenario_id = await _scenario_id_of(client, tokens, demo_version_id)

    first = await client.post(
        f"/api/v1/scenarios/{scenario_id}/archive", headers=auth(tokens["instructor1"])
    )
    assert first.status_code == 200
    first_archived_at = first.json()["archived_at"]

    second = await client.post(
        f"/api/v1/scenarios/{scenario_id}/archive", headers=auth(tokens["instructor1"])
    )
    assert second.status_code == 200
    assert second.json()["archived_at"] == first_archived_at


async def test_archive_is_instructor_only(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    scenario_id = await _scenario_id_of(client, tokens, demo_version_id)

    refused = await client.post(
        f"/api/v1/scenarios/{scenario_id}/archive", headers=auth(tokens["trainee1"])
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_archive_of_an_unknown_scenario_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/scenarios/00000000-0000-4000-8000-000000000000/archive",
        headers=auth(tokens["instructor1"]),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_a_running_session_is_unaffected_by_archiving_its_scenario(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    isolated_scenario_catalog: None,
    demo_version_id: ScenarioVersionId,
) -> None:
    """Archiving a scenario touches no `scenario_versions` row and no session (D4, ТЗ ¶229): a
    session already running on one of its versions keeps working exactly as before."""
    scenario_id = await _scenario_id_of(client, tokens, demo_version_id)
    session = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [
            participant(users["trainee1"], "OPERATOR_112"),
            participant(users["trainee2"], "DDS"),
        ],
    )
    session_id = session["id"]

    archived = await client.post(
        f"/api/v1/scenarios/{scenario_id}/archive", headers=auth(tokens["instructor1"])
    )
    assert archived.status_code == 200, archived.text

    still_readable = await client.get(
        f"/api/v1/sessions/{session_id}", headers=auth(tokens["instructor1"])
    )
    assert still_readable.status_code == 200, still_readable.text
    assert still_readable.json()["id"] == session_id

    still_startable = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert still_startable.status_code == 200, still_startable.text
