"""E16's own invariant: **a report for an unfinished session is refused**
(`docs/hld/90-tbd-epics.md`'s E16 row, SPEC §29, D11).

The epics table states it as a one-line guarantee, and it is the load-bearing one of this epic:
the report is the artefact a trainee is assessed by, so a session that has not finished must not
produce one — not a partial one, not an optimistic one, not one that silently scores a running
attempt. `409 REPORT_NOT_READY` is the whole answer, for every way a session can fail to be
finished:

* `ACTIVE` — the DDS stage is still running;
* `ROLE_TRANSITION` — the 112 stage is done and the DDS stage has not started;
* `ABORTED` — the instructor stopped it, and an aborted session is **never scored** (E16 R1), so
  it has no numbers to report either;
* `COMPLETED` but with no stored `score_results` — the session finished, but scoring left
  nothing (a `ScoringEvidenceError` at close, for instance). The report reads stored scores and
  never recomputes them (R1), so "finished" alone is not enough.

The file is deliberately an end-to-end one: the guard it protects lives in
`app.application.reports.assemble_report`, but the invariant is about what a *client* can get,
and a guard that is bypassed by the route would pass a unit test.

**Bite proof.** The two `raise ReportNotReadyError` lines were temporarily removed from
`GetSessionReport.__call__` (replaced by `stored_results = await uow.scores.load_report(...) or
()`), and all **five** tests below failed: the instructor cases rendered a `200` report for a
running, a transitioning and an aborted session, and the trainee case reached the *release* gate
instead and answered `403 REPORT_NOT_RELEASED` — which is the sharpest evidence that the state
check is what stops this and nothing downstream does. The guard was restored and all five pass.
The captured output is in `/tmp/teamwork-112-maxxing/reports/e16-a.md` under "INVARIANT BITE
PROOF".
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from tests.api.conftest import auth

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------------------------
# Fixtures, re-exported by name (`pytest_plugins` cannot register an already-loaded conftest —
# the same pattern `test_inv_09_rescore_endpoint.py` uses).
# ---------------------------------------------------------------------------------------------

from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.handoff import conftest as _handoff_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402
from tests.api.reports import conftest as _report_fixtures  # noqa: E402

OperatorFlow = _handoff_fixtures.OperatorFlow

client = _api_fixtures.client
clean_database = _api_fixtures.clean_database
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

api_settings = _report_fixtures.api_settings
_api_settings_base = _report_fixtures._api_settings_base
resolved = _report_fixtures.resolved
completed = _report_fixtures.completed


async def _report(flow: OperatorFlow) -> Any:
    return await flow.client.get(
        f"/api/v1/reports/{flow.session_id}", headers=auth(flow.instructor_token)
    )


def _assert_refused(response: Any) -> None:
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "REPORT_NOT_READY"
    assert "score_report" not in body, "a refusal must carry no numbers at all"


# ---------------------------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------------------------


async def test_an_active_session_has_no_report(dds_active: OperatorFlow) -> None:
    """The DDS stage is live: the session is `ACTIVE` and nothing has been scored."""
    _assert_refused(await _report(dds_active))


async def test_a_session_in_role_transition_has_no_report(
    in_transition: OperatorFlow,
) -> None:
    """The 112 stage finished and the DDS stage has not started — half a session is not one."""
    _assert_refused(await _report(in_transition))


async def test_an_aborted_session_has_no_report(dds_active: OperatorFlow) -> None:
    """E16 R1: an `ABORTED` session is never scored, so it has no report either — and in
    particular it does not get an empty-but-successful one."""
    aborted = await dds_active.client.post(
        f"/api/v1/sessions/{dds_active.session_id}/abort",
        headers=auth(dds_active.instructor_token),
        json={"reason": "учебная остановка"},
    )
    assert aborted.status_code == 200, aborted.text

    _assert_refused(await _report(dds_active))


async def test_a_completed_session_whose_scores_are_missing_has_no_report(
    completed: OperatorFlow, uow_factory: Any
) -> None:
    """ "Finished" is not enough: the report *reads* stored scores (R1) and refuses when there
    are none, rather than quietly recomputing them into a report nobody audited."""
    assert (await _report(completed)).status_code == 200, "the baseline: it works when scored"

    async with uow_factory() as uow:
        await uow.session.execute(
            sa.text("DELETE FROM score_results WHERE session_id = :s"),
            {"s": completed.session_id},
        )
        await uow.commit()

    _assert_refused(await _report(completed))


async def test_a_trainee_gets_the_same_refusal(dds_active: OperatorFlow) -> None:
    """The refusal is about the session, not about the reader: a trainee learns exactly the same
    thing the instructor does, and no more."""
    response = await dds_active.client.get(
        f"/api/v1/reports/{dds_active.session_id}",
        headers=auth(dds_active.operator_token),
    )
    _assert_refused(response)
