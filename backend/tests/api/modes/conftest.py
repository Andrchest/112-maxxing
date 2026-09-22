"""Fixtures for the per-mode API tests (E17-D, R6) — real HTTP, a movable clock.

R6 asks for "one API-level test module per mode": `SINGLE_ROLE [OPERATOR_112]`,
`SINGLE_ROLE [DDS]` (prefab), `FULL_CYCLE_SINGLE_TRAINEE`, `MULTI_TRAINEE` with two distinct
users, `ASSESSMENT`. Every fixture the 112 -> DDS chain already needs — the `FakeClock` container,
`OperatorFlow`, the DDS-side levers, the DDS-only prefab scenario — already exists in
`tests.api.handoff.conftest` and `tests.api.dds.conftest`; this module re-exports it by name
(the same pattern `tests/api/dds/conftest.py` and `tests/invariants/test_inv_09_rescore_endpoint.py`
use, and `pytest_plugins` cannot register an already-loaded conftest) and adds the two things no
existing package needed:

* an `OPERATOR_112`-only scenario version (`role_chain: [OPERATOR_112]`), for `SINGLE_ROLE
  [OPERATOR_112]` and `ASSESSMENT` — both need a chain that completes without ever reaching a
  `DDS` stage, so `SESSION_COMPLETED` fires from `completeOperatorStage` directly and no
  `ROLE_TRANSITION` is ever entered;
* a `FULL_CYCLE_SINGLE_TRAINEE` starter — `tests.api.operator.conftest`'s own `_start_session`
  is hard-wired to `MULTI_TRAINEE` (one participant per stage), so a session where **one**
  participant plays every stage (`assigned_role_type: null`, §10.10) needs its own builder.

Every fixture built here reuses `OperatorFlow` as-is: its `operator_token`/`dds_token` fields are
just "the token this flow's HTTP helpers default to" and "the token the DDS-side helpers of
`tests.api.dds.conftest` use" — nothing in the dataclass or in those helpers assumes the two
tokens name different users, so a `FULL_CYCLE_SINGLE_TRAINEE` flow simply sets both to the one
trainee who plays the whole chain.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from app.api.container import Container
from app.domain.common.ids import ScenarioVersionId, UserId

from tests.api import conftest as _api_fixtures
from tests.api.conftest import auth, create_demo_session, participant
from tests.api.dds import conftest as _dds_fixtures
from tests.api.handoff import conftest as _handoff_fixtures
from tests.api.operator import conftest as _operator_fixtures

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------------------------
# Fixtures, re-exported by name (see the module docstring)
# ---------------------------------------------------------------------------------------------

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

clock = _handoff_fixtures.clock
container = _handoff_fixtures.container
idempotency = _handoff_fixtures.idempotency
_remove_this_packages_scenarios = _handoff_fixtures._remove_this_packages_scenarios

OperatorFlow = _handoff_fixtures.OperatorFlow
flow = _operator_fixtures.flow
ringing = _operator_fixtures.ringing
connected = _operator_fixtures.connected
interview = _operator_fixtures.interview
uow_factory = _operator_fixtures.uow_factory

prepared = _handoff_fixtures.prepared
handed_off = _handoff_fixtures.handed_off
in_transition = _handoff_fixtures.in_transition
dds_active = _handoff_fixtures.dds_active
dds_only_version_id = _handoff_fixtures.dds_only_version_id
dds_only_session = _handoff_fixtures.dds_only_session
fill_card = _handoff_fixtures.fill_card
prepare_handoff = _handoff_fixtures.prepare_handoff
raw_role_chain_version = _handoff_fixtures.raw_role_chain_version
read_assignments = _handoff_fixtures.read_assignments

acknowledge = _dds_fixtures.acknowledge
open_selection = _dds_fixtures.open_selection
board = _dds_fixtures.board
select = _dds_fixtures.select
dispatch = _dds_fixtures.dispatch
work_item = _dds_fixtures.work_item
event_types = _dds_fixtures.event_types
events_of = _dds_fixtures.events_of
at = _dds_fixtures.at
session_offset_ms = _dds_fixtures.session_offset_ms
dds_post = _dds_fixtures.dds_post
dds_get = _dds_fixtures.dds_get


# ---------------------------------------------------------------------------------------------
# An OPERATOR_112-only scenario (`SINGLE_ROLE [OPERATOR_112]`, `ASSESSMENT`)
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def operator_only_version_id(unit_of_work: Any) -> ScenarioVersionId:
    """The demo document with `role_chain: [OPERATOR_112]` — completes with no `DDS` stage at all.

    The mirror image of `dds_only_version_id` (`tests.api.handoff.conftest`): that one exists for
    `requires_prefab_handoff_for_dds_only`, this one for the modes whose policy needs a chain that
    ends the *session* the moment the one stage it has completes (`SessionPolicy.role_chain_length`
    is `"ONE_OR_MORE"` for `ASSESSMENT` and `"EXACTLY_ONE"` for `SINGLE_ROLE` — one entry satisfies
    both), instead of moving to `ROLE_TRANSITION`.
    """
    return await raw_role_chain_version(unit_of_work, "operator-only-single-role", ["OPERATOR_112"])


# ---------------------------------------------------------------------------------------------
# SINGLE_ROLE [OPERATOR_112]
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def single_role_operator_flow(
    client: Any,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    operator_only_version_id: ScenarioVersionId,
) -> OperatorFlow:
    """A started `SINGLE_ROLE` session on the `[OPERATOR_112]`-only scenario, played by `trainee1`.

    `dds_token`/`dds_user_id` are filled with `trainee2` only because the dataclass requires
    them; nothing in this mode ever issues a `DDS` command.
    """
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        operator_only_version_id,
        [participant(users["trainee1"], "OPERATOR_112")],
        session_mode="SINGLE_ROLE",
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    return OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )


# ---------------------------------------------------------------------------------------------
# FULL_CYCLE_SINGLE_TRAINEE
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def full_cycle_flow(
    client: Any,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    demo_version_id: ScenarioVersionId,
) -> OperatorFlow:
    """A started `FULL_CYCLE_SINGLE_TRAINEE` session, `trainee1` bound to every stage of it.

    `assigned_role_type: null` is §10.10's `ALL_STAGES_ONE_PARTICIPANT`: `trainee1` plays both the
    `OPERATOR_112` and the `DDS` stage, so `operator_token` and `dds_token` are deliberately the
    same token — the same participant is who `continueToNextStage` and the DDS-side helpers act
    as once the hand-over completes.
    """
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        demo_version_id,
        [participant(users["trainee1"], None)],
        session_mode="FULL_CYCLE_SINGLE_TRAINEE",
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    return OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee1"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee1"],
    )


# ---------------------------------------------------------------------------------------------
# ASSESSMENT
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def assessment_flow(
    client: Any,
    container: Container,
    tokens: dict[str, str],
    users: dict[str, UserId],
    operator_only_version_id: ScenarioVersionId,
) -> OperatorFlow:
    """A started `ASSESSMENT` session on the `[OPERATOR_112]`-only scenario, played by `trainee1`.

    Reuses the same one-stage scenario `single_role_operator_flow` does: `ASSESSMENT`'s
    `assignment_rule` (`SINGLE_STAGE_ONE_PARTICIPANT`, §10.10) binds exactly one participant to
    exactly one stage, so a longer `role_chain` would leave its other stages unbound and refuse
    `validate` — an `ASSESSMENT` session in this repository is therefore a single-stage one, same
    as `SINGLE_ROLE`, just with `show_asr_partials=False` and
    `report_visible_to_trainee_before_release=False` (see the R6 test module's docstring for why).
    """
    detail = await create_demo_session(
        client,
        tokens["instructor1"],
        operator_only_version_id,
        [participant(users["trainee1"], "OPERATOR_112")],
        session_mode="ASSESSMENT",
    )
    session_id = UUID(detail["id"])
    started = await client.post(
        f"/api/v1/sessions/{session_id}/start", headers=auth(tokens["instructor1"])
    )
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "ACTIVE"
    return OperatorFlow(
        client=client,
        container=container,
        session_id=session_id,
        operator_token=tokens["trainee1"],
        dds_token=tokens["trainee2"],
        instructor_token=tokens["instructor1"],
        operator_user_id=users["trainee1"],
        dds_user_id=users["trainee2"],
    )


async def report(flow: OperatorFlow, *, token: str | None = None) -> Any:
    """`getSessionReport` as the instructor unless another token is given."""
    return await flow.client.get(
        f"/api/v1/reports/{flow.session_id}",
        headers=auth(token or flow.instructor_token),
    )


async def release(flow: OperatorFlow, *, token: str | None = None) -> Any:
    """`releaseReportToTrainee`."""
    return await flow.client.post(
        f"/api/v1/instructor/sessions/{flow.session_id}/report/release",
        headers=auth(token or flow.instructor_token),
    )
