"""`listSessionComments` / `createSessionComment` over HTTP (I4 E32, `71-i4-wave4.md` §71.9).

Three acceptance items from `90-tbd-epics.md`'s "### E32" section:

* comment visibility equals report visibility (the trainee gets the session's report gate,
  `403 REPORT_NOT_RELEASED` before release, `200` after);
* an edit adds a row and never updates one (`superseded` flips on the row it replaces);
* the account-role gate on the write side (`INSTRUCTOR`/`ADMIN` only).
"""

from __future__ import annotations

import httpx
import pytest

from tests.api.conftest import auth
from tests.api.reports.conftest import OperatorFlow, release

pytestmark = pytest.mark.integration


async def _comments(flow: OperatorFlow, *, token: str) -> httpx.Response:
    return await flow.client.get(f"/api/v1/reports/{flow.session_id}/comments", headers=auth(token))


async def _post_comment(flow: OperatorFlow, *, token: str, **body: object) -> httpx.Response:
    return await flow.client.post(
        f"/api/v1/reports/{flow.session_id}/comments", headers=auth(token), json=body
    )


async def test_comment_visibility_equals_report_visibility(completed: OperatorFlow) -> None:
    """MULTI_TRAINEE needs a release; the trainee's comment read follows exactly that gate."""
    created = await _post_comment(
        completed, token=completed.instructor_token, text="Хорошая работа с картой вызова."
    )
    assert created.status_code == 201, created.text
    comment = created.json()
    assert comment["text"] == "Хорошая работа с картой вызова."
    assert comment["session_id"] == str(completed.session_id)
    assert comment["lesson_id"] is None
    assert comment["superseded"] is False
    assert comment["replaces_comment_id"] is None

    # Instructor always sees it.
    as_instructor = await _comments(completed, token=completed.instructor_token)
    assert as_instructor.status_code == 200
    assert len(as_instructor.json()["items"]) == 1

    # Trainee (participant) is refused before release — the same gate `getSessionReport` uses.
    before_release = await _comments(completed, token=completed.operator_token)
    assert before_release.status_code == 403, before_release.text
    assert before_release.json()["code"] == "REPORT_NOT_RELEASED"

    released = await release(completed)
    assert released.status_code == 200, released.text

    after_release = await _comments(completed, token=completed.operator_token)
    assert after_release.status_code == 200, after_release.text
    items = after_release.json()["items"]
    assert len(items) == 1
    assert items[0]["text"] == "Хорошая работа с картой вызова."


async def test_an_edit_adds_a_row_and_marks_the_original_superseded(
    completed: OperatorFlow,
) -> None:
    """`replaces_comment_id` makes an edit a new row; the row it replaces becomes `superseded`."""
    first = await _post_comment(
        completed, token=completed.instructor_token, text="Первая версия комментария."
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["comment_id"]

    edited = await _post_comment(
        completed,
        token=completed.instructor_token,
        text="Исправленная версия комментария.",
        replaces_comment_id=first_id,
    )
    assert edited.status_code == 201, edited.text
    assert edited.json()["replaces_comment_id"] == first_id
    assert edited.json()["superseded"] is False

    listed = await _comments(completed, token=completed.instructor_token)
    items = {item["comment_id"]: item for item in listed.json()["items"]}
    assert len(items) == 2, "the edit is a new row — never an UPDATE"
    assert items[first_id]["superseded"] is True
    assert items[first_id]["text"] == "Первая версия комментария."
    assert items[edited.json()["comment_id"]]["superseded"] is False


async def test_replaces_an_unknown_comment_is_404(completed: OperatorFlow) -> None:
    response = await _post_comment(
        completed,
        token=completed.instructor_token,
        text="…",
        replaces_comment_id="00000000-0000-4000-8000-000000000000",
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_create_comment_is_instructor_only(completed: OperatorFlow) -> None:
    refused = await _post_comment(
        completed, token=completed.operator_token, text="Я не должен уметь это делать."
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_empty_text_is_422(completed: OperatorFlow) -> None:
    response = await _post_comment(completed, token=completed.instructor_token, text="")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_comments_on_an_unknown_session_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/reports/00000000-0000-4000-8000-000000000000/comments",
        headers=auth(tokens["instructor1"]),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
