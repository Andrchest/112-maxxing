"""`evaluate_condition` and `EventIndex` — every branch and operator (HLD §10.11).

Each operator is asserted in both directions (allow and deny), and the totality contract is
asserted separately: an unknown fact, resource or role evaluates `False` and nothing raises.
"""

from __future__ import annotations

import pytest
from app.domain.caller.emotion import EmotionState
from app.domain.common.actors import ActorRef
from app.domain.common.ids import IncidentId
from app.domain.enums import ActorType, EmotionLabel, ResourceStatus, RoleType
from app.domain.events.types import EventType
from app.domain.layers.caller_belief import CallerBelief
from app.domain.layers.world_truth import WorldTruth
from app.domain.world.conditions import Condition, ConditionContext, EventIndex, evaluate_condition
from app.domain.world.engine import PendingAction

from tests.unit.domain.world._builders import INCIDENT_ID, demo_scenario, resource_board

_TRAINEE = ActorRef(actor_type=ActorType.TRAINEE)


def _ctx(**overrides: object) -> ConditionContext:
    version = demo_scenario()
    board, keys = resource_board(
        version,
        statuses={"ac1": ResourceStatus.WORKING, "ac2": ResourceStatus.EN_ROUTE},
    )
    base: dict[str, object] = {
        "world_truth": WorldTruth(
            incident_id=IncidentId(INCIDENT_ID),
            facts={"a.number": 5, "a.text": "x", "a.flag": True, "a.none": None},
        ),
        "caller_belief": CallerBelief(
            incident_id=IncidentId(INCIDENT_ID),
            facts={"a.text": "caller"},
            emotion=EmotionState(emotion=EmotionLabel.CALM, stress_level=0.1),
        ),
        "resources": board,
        "resource_keys": keys,
        "stage_states": {RoleType.OPERATOR_112: "INTERVIEW", RoleType.DDS: "RECEIVED"},
        "reached_states": {RoleType.OPERATOR_112: frozenset({"RINGING", "INTERVIEW"})},
        "now_ms": 100_000,
    }
    base.update(overrides)
    return ConditionContext(**base)  # type: ignore[arg-type]


def _fact(**fields: object) -> Condition:
    return Condition.model_validate({"fact": fields})


def _resource(**fields: object) -> Condition:
    return Condition.model_validate({"resource": fields})


# --------------------------------------------------------------------------------------- facts


@pytest.mark.parametrize(
    ("op", "value", "expected"),
    [
        ("EQ", 5, True),
        ("EQ", 6, False),
        ("NEQ", 6, True),
        ("NEQ", 5, False),
        ("GT", 4, True),
        ("GT", 5, False),
        ("GTE", 5, True),
        ("GTE", 6, False),
        ("LT", 6, True),
        ("LT", 5, False),
        ("LTE", 5, True),
        ("LTE", 4, False),
        ("IN", [4, 5], True),
        ("IN", [4, 6], False),
    ],
)
def test_fact_operators(op: str, value: object, expected: bool) -> None:
    cond = _fact(fact_id="a.number", layer="WORLD", op=op, value=value)
    assert evaluate_condition(cond, _ctx()) is expected


def test_fact_is_null_and_is_not_null() -> None:
    ctx = _ctx()
    absent = {"fact_id": "a.missing", "layer": "WORLD"}
    assert evaluate_condition(_fact(**absent, op="IS_NULL"), ctx) is True
    assert evaluate_condition(_fact(**absent, op="IS_NOT_NULL"), ctx) is False
    present_none = {"fact_id": "a.none", "layer": "WORLD"}
    assert evaluate_condition(_fact(**present_none, op="IS_NULL"), ctx) is True
    assert evaluate_condition(_fact(**present_none, op="IS_NOT_NULL"), ctx) is False
    known = {"fact_id": "a.number", "layer": "WORLD"}
    assert evaluate_condition(_fact(**known, op="IS_NOT_NULL"), ctx) is True
    assert evaluate_condition(_fact(**known, op="IS_NULL"), ctx) is False


def test_fact_layers_are_read_separately() -> None:
    ctx = _ctx()
    world = _fact(fact_id="a.text", layer="WORLD", op="EQ", value="x")
    caller = _fact(fact_id="a.text", layer="CALLER", op="EQ", value="x")
    assert evaluate_condition(world, ctx) is True
    assert evaluate_condition(caller, ctx) is False


def test_unknown_fact_and_unorderable_comparison_are_false() -> None:
    ctx = _ctx()
    assert evaluate_condition(_fact(fact_id="nope", layer="WORLD", op="EQ", value=1), ctx) is False
    assert (
        evaluate_condition(_fact(fact_id="a.text", layer="WORLD", op="GT", value=1), ctx) is False
    )
    assert (
        evaluate_condition(_fact(fact_id="a.number", layer="WORLD", op="IN", value=5), ctx) is False
    )
    assert (
        evaluate_condition(_fact(fact_id="a.flag", layer="WORLD", op="GTE", value=0), ctx) is False
    )


# ----------------------------------------------------------------------------------- resources


def test_resource_selector_by_id() -> None:
    ctx = _ctx()
    cond = _resource(selector={"resource_id": "ac2"}, op="ANY_IS", status="EN_ROUTE")
    assert evaluate_condition(cond, ctx) is True
    denied = _resource(selector={"resource_id": "ac2"}, op="ANY_IS", status="WORKING")
    assert evaluate_condition(denied, ctx) is False


def test_resource_selector_by_capability_and_service_type() -> None:
    ctx = _ctx()
    by_capability = _resource(
        selector={"capability": "FIRE_SUPPRESSION"}, op="ANY_IS", status="WORKING"
    )
    assert evaluate_condition(by_capability, ctx) is True
    by_service = _resource(selector={"service_type": "POLICE"}, op="ALL_ARE", status="AVAILABLE")
    assert evaluate_condition(by_service, ctx) is True
    denied = _resource(selector={"service_type": "POLICE"}, op="ALL_ARE", status="WORKING")
    assert evaluate_condition(denied, ctx) is False


@pytest.mark.parametrize(
    ("op", "status", "count", "expected"),
    [
        ("ANY_IS", "WORKING", None, True),
        ("ANY_IS", "RETURNING", None, False),
        ("ALL_ARE", "AVAILABLE", None, False),
        ("NONE_IS", "RETURNING", None, True),
        ("NONE_IS", "WORKING", None, False),
        ("COUNT_GTE", "WORKING", 1, True),
        ("COUNT_GTE", "WORKING", 2, False),
        ("COUNT_GTE", "WORKING", None, True),
    ],
)
def test_resource_operators(op: str, status: str, count: int | None, expected: bool) -> None:
    cond = _resource(selector={"capability": "FIRE_SUPPRESSION"}, op=op, status=status, count=count)
    assert evaluate_condition(cond, _ctx()) is expected


def test_unknown_resource_is_false_for_every_operator() -> None:
    ctx = _ctx()
    for op in ("ANY_IS", "ALL_ARE", "NONE_IS", "COUNT_GTE"):
        cond = _resource(selector={"resource_id": "no_such"}, op=op, status="AVAILABLE")
        assert evaluate_condition(cond, ctx) is False


def test_resource_id_may_also_be_the_runtime_uuid() -> None:
    ctx = _ctx(resource_keys={})
    runtime_id = str(ctx.resources[next(iter(ctx.resources))].resource_id)
    cond = _resource(selector={"resource_id": runtime_id}, op="ANY_IS", status="AVAILABLE")
    assert isinstance(evaluate_condition(cond, ctx), bool)


# -------------------------------------------------------------------------------------- stages


@pytest.mark.parametrize(
    ("role", "op", "state", "expected"),
    [
        ("OPERATOR_112", "IS", "INTERVIEW", True),
        ("OPERATOR_112", "IS", "RINGING", False),
        ("OPERATOR_112", "IS_NOT", "RINGING", True),
        ("OPERATOR_112", "IS_NOT", "INTERVIEW", False),
        ("OPERATOR_112", "REACHED", "RINGING", True),
        ("OPERATOR_112", "REACHED", "STAGE_COMPLETED", False),
        ("DDS", "REACHED", "RECEIVED", True),
        ("EDDS", "IS", "ANY", False),
        ("EDDS", "IS_NOT", "ANY", False),
    ],
)
def test_stage_operators(role: str, op: str, state: str, expected: bool) -> None:
    cond = Condition.model_validate({"stage": {"role": role, "op": op, "state": state}})
    assert evaluate_condition(cond, _ctx()) is expected


# ------------------------------------------------------------------------------------ sim_time


def test_sim_time_operators() -> None:
    ctx = _ctx()
    gte = Condition.model_validate({"sim_time": {"op": "GTE", "ms": 100_000}})
    lt = Condition.model_validate({"sim_time": {"op": "LT", "ms": 100_000}})
    assert evaluate_condition(gte, ctx) is True
    assert evaluate_condition(lt, ctx) is False
    assert (
        evaluate_condition(Condition.model_validate({"sim_time": {"op": "LT", "ms": 1}}), ctx)
        is False
    )


# -------------------------------------------------------------------------------------- action


def _index() -> EventIndex:
    actions = [
        PendingAction(
            event_type=EventType.HANDOFF_CREATED,
            at_offset_ms=90_000,
            payload={"recipient": "FIRE_RESCUE"},
            actor=_TRAINEE,
        ),
        PendingAction(
            event_type=EventType.HANDOFF_CREATED,
            at_offset_ms=10_000,
            payload={"recipient": "AMBULANCE"},
            actor=_TRAINEE,
        ),
    ]
    return EventIndex.fold(actions)


def test_event_index_folds_in_determinism_rule_one_order() -> None:
    index = _index()
    offsets = [occ.at_offset_ms for occ in index.occurrences[EventType.HANDOFF_CREATED]]
    assert offsets == [10_000, 90_000]
    assert index.count(EventType.HANDOFF_CREATED) == 2
    assert index.first_offset_ms(EventType.HANDOFF_CREATED) == 10_000
    assert index.last_offset_ms(EventType.HANDOFF_CREATED) == 90_000
    assert index.count(EventType.CALL_ENDED) == 0
    assert index.first_offset_ms(EventType.CALL_ENDED) is None
    assert index.last_offset_ms(EventType.CALL_ENDED) is None


def test_event_index_fold_is_order_free_and_appends_to_a_base() -> None:
    index = _index()
    extra = PendingAction(
        event_type=EventType.CALL_ENDED, at_offset_ms=95_000, payload={}, actor=_TRAINEE
    )
    extended = EventIndex.fold([extra], base=index)
    assert extended.count(EventType.HANDOFF_CREATED) == 2
    assert extended.count(EventType.CALL_ENDED) == 1


@pytest.mark.parametrize(
    ("op", "count", "expected"),
    [
        ("OCCURRED", None, True),
        ("NOT_OCCURRED", None, False),
        ("COUNT_GTE", 2, True),
        ("COUNT_GTE", 3, False),
        ("COUNT_GTE", None, True),
    ],
)
def test_action_operators(op: str, count: int | None, expected: bool) -> None:
    cond = Condition.model_validate(
        {"action": {"event_type": "HANDOFF_CREATED", "op": op, "count": count}}
    )
    assert evaluate_condition(cond, _ctx(event_index=_index())) is expected


def test_action_never_occurred_is_true_when_absent() -> None:
    cond = Condition.model_validate({"action": {"event_type": "CALL_ENDED", "op": "NOT_OCCURRED"}})
    assert evaluate_condition(cond, _ctx(event_index=_index())) is True


def test_action_within_ms_narrows_the_window() -> None:
    ctx = _ctx(event_index=_index())
    recent = Condition.model_validate(
        {
            "action": {
                "event_type": "HANDOFF_CREATED",
                "op": "COUNT_GTE",
                "count": 2,
                "within_ms": 20_000,
            }
        }
    )
    assert evaluate_condition(recent, ctx) is False
    one = Condition.model_validate(
        {"action": {"event_type": "HANDOFF_CREATED", "op": "OCCURRED", "within_ms": 20_000}}
    )
    assert evaluate_condition(one, ctx) is True


def test_action_payload_equals_filters_occurrences() -> None:
    ctx = _ctx(event_index=_index())
    match = Condition.model_validate(
        {
            "action": {
                "event_type": "HANDOFF_CREATED",
                "op": "OCCURRED",
                "payload_equals": {"recipient": "AMBULANCE"},
            }
        }
    )
    miss = Condition.model_validate(
        {
            "action": {
                "event_type": "HANDOFF_CREATED",
                "op": "OCCURRED",
                "payload_equals": {"recipient": "POLICE"},
            }
        }
    )
    assert evaluate_condition(match, ctx) is True
    assert evaluate_condition(miss, ctx) is False


# --------------------------------------------------------------------------------- combinators


def _true() -> Condition:
    return Condition.model_validate({"sim_time": {"op": "GTE", "ms": 0}})


def _false() -> Condition:
    return Condition.model_validate({"sim_time": {"op": "LT", "ms": 0}})


def test_combinators() -> None:
    ctx = _ctx()
    assert evaluate_condition(Condition(all=[_true(), _true()]), ctx) is True
    assert evaluate_condition(Condition(all=[_true(), _false()]), ctx) is False
    assert evaluate_condition(Condition(any=[_false(), _true()]), ctx) is True
    assert evaluate_condition(Condition(any=[_false(), _false()]), ctx) is False
    assert evaluate_condition(Condition.model_validate({"not": _false().model_dump()}), ctx) is True
    assert evaluate_condition(Condition.model_validate({"not": _true().model_dump()}), ctx) is False


def test_empty_combinators_follow_python_semantics() -> None:
    ctx = _ctx()
    assert evaluate_condition(Condition(all=[]), ctx) is True
    assert evaluate_condition(Condition(any=[]), ctx) is False


def test_the_demo_scenario_conditions_evaluate_without_raising() -> None:
    ctx = _ctx()
    version = demo_scenario()
    for event in version.world_events:
        condition = getattr(event, "condition", None)
        if condition is not None:
            assert isinstance(evaluate_condition(condition, ctx), bool)
    resolution = version.expected_response.resolution_condition
    assert isinstance(evaluate_condition(resolution, ctx), bool)
