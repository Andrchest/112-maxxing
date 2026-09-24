"""INV 3 — "DDS cannot read hidden WorldTruth to repair an incomplete handoff" (SPEC §42 item 3).

SPEC §3 states the case this invariant exists for in numbers: the world says the fire is at house
**27**; the caller believes and the operator types **72**. DDS must receive "72". It must not
obtain "27" from `WorldTruth`, and a fact the operator never entered must stay absent.

As with INV 4, the invariant has a structural half and a behavioural half, and the structural one
is the real guarantee.

**(a) Structural.** An `ast` scan of the DDS-facing modules — `application/handoff/work_item.py`,
everything under `application/dds/` and every `app/api/routers` module that serves the `dds` tag —
asserts that none of them, and no constructor or function signature in them, names the
world-truth, caller-belief or operator-card repository, port or domain type. D3's words: "the DDS
application services and API handlers are constructed without a `WorldTruth` repository: they
cannot read it because they are never given it". A scan of the imports is how "cannot" is checked.

Two additions E9-B makes to that scan. The forbidden set now includes the **operator-card**
repository and the live `OperatorCard` type: the DDS side sees what the operator typed only
through the frozen `HandoffSnapshot`, so a path to the live card would break §42 test 3 exactly as
a path to world truth would. (`CARD_FIELDS` is deliberately still allowed — it is the public field
*specification* every client already receives, not card data.) And the constructor signatures of
every DDS use case are inspected directly, by parameter *type*, because "constructed without" is a
claim about what a service is handed, not only about what its module mentions.

**(b) Behavioural.** A full Operator 112 stage over real HTTP on the demo scenario — whose world
truth genuinely says `address.house = "27"` — in which the trainee types "72" and never sends
`address.floor` at all. Then `createHandoff`, `completeOperatorStage`, `continueToNextStage`, and
every DDS-visible surface is searched *as raw JSON* for the string "27": the work item, the
session snapshot, the REST event page and the WebSocket frames the DDS connection receives. The
omitted field must be absent everywhere, and `missing_field_paths` must name the gaps it leaves
rather than fill them.

Searching the serialised JSON rather than named fields is deliberate: a leak that arrived in a
key nobody thought to assert on would still be a leak.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from app.domain.common.ids import SessionId
from app.domain.events.types import EventType
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

BACKEND = Path(__file__).resolve().parents[2]
APPLICATION = BACKEND / "app" / "application"
ROUTERS = BACKEND / "app" / "api" / "routers"

# ---------------------------------------------------------------------------------------------
# (a) Structural
# ---------------------------------------------------------------------------------------------

#: The names no DDS-facing module may mention: the two engine-written layers and the live
#: operator card, with their ports and their adapters. `HandoffSnapshot` and `DDSAssignment` are
#: deliberately absent — those are exactly what the DDS side is *supposed* to read, and so is
#: `CARD_FIELDS`, which is the field specification every client already gets.
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "WorldTruth",
        "WorldTruthRepository",
        "SqlAlchemyWorldTruthRepository",
        "world_truth",
        "world_truth_repository",
        "CallerBelief",
        "CallerBeliefRepository",
        "SqlAlchemyCallerBeliefRepository",
        "caller_belief",
        "caller_beliefs",
        "caller_belief_repository",
        "instantiate_world_truth",
        "instantiate_caller_belief",
        "OperatorCard",
        "OperatorCardRepository",
        "SqlAlchemyOperatorCardRepository",
        "operator_cards",
        "operator_card_repository",
    }
)

#: Every DDS use case the container builds, by container factory name (E9-B). The list is checked
#: against `app.api.container` itself, so a factory added to that block without being named here
#: fails the guard test below rather than escaping the signature scan.
DDS_CONTAINER_FACTORIES: tuple[str, ...] = (
    "dds_command_gate",
    "get_dds_work_item",
    "list_dds_resources",
    "acknowledge_dds_assignment",
    "open_dds_resource_selection",
    "back_to_dds_acknowledged",
    "select_dds_resource",
    "deselect_dds_resource",
    "dispatch_dds_resources",
    "send_dds_status_update",
    "list_notifications",
    "acknowledge_notification",
    "list_radio_messages",
    "close_dds_incident",
    "dds_stage_automation",
)

#: The module that projects the DDS work item — the one place a repair could be smuggled in.
WORK_ITEM = APPLICATION / "handoff" / "work_item.py"

#: E9-B's DDS command package. It does not exist yet; when it does, every module joins the scan.
DDS_PACKAGE = APPLICATION / "dds"


def _dds_router_modules() -> list[Path]:
    """Every `app/api/routers` module that registers an operation of the `dds` tag."""
    return sorted(
        path
        for path in ROUTERS.glob("*.py")
        if path.name != "__init__.py" and 'tags=["dds"]' in path.read_text(encoding="utf-8")
    )


def dds_facing_modules() -> list[Path]:
    """Every module this invariant scans, in a stable order."""
    modules = [WORK_ITEM]
    if DDS_PACKAGE.is_dir():
        modules.extend(sorted(path for path in DDS_PACKAGE.rglob("*.py")))
    modules.extend(_dds_router_modules())
    return modules


def _mentioned_names(path: Path) -> set[str]:
    """Every identifier this module imports, calls, annotates with or reaches as an attribute.

    Wide on purpose: an import, a type annotation on a constructor parameter, a `uow.world_truth`
    attribute access and a bare name all count. A module that mentions none of the forbidden
    names cannot reach the layers they name.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.update(node.module.split("."))
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_the_scan_covers_the_modules_it_claims_to() -> None:
    """A guard on the guard: the work-item projection must be in the scan, and must exist."""
    modules = dds_facing_modules()
    assert WORK_ITEM in modules
    assert WORK_ITEM.is_file()
    if DDS_PACKAGE.is_dir():
        assert any(path.parent == DDS_PACKAGE for path in modules), (
            "application/dds/ exists but nothing under it is scanned"
        )


@pytest.mark.parametrize("path", dds_facing_modules(), ids=lambda path: path.name)
def test_no_dds_facing_module_can_reach_world_truth(path: Path) -> None:
    """SPEC §42 test 3, structurally: the layers DDS may not see are unreachable from here."""
    offenders = sorted(_mentioned_names(path) & FORBIDDEN_NAMES)
    assert not offenders, (
        f"{path.relative_to(BACKEND)} mentions {offenders}: a DDS-facing module must have no "
        "path to WorldTruth or CallerBelief (SPEC §42 test 3, D3)"
    )


def test_the_work_item_projection_takes_no_repository_at_all() -> None:
    """`work_item_view` is a pure function of a snapshot and its legs — it holds nothing."""
    import inspect

    from app.application.handoff.work_item import work_item_view

    parameters = list(inspect.signature(work_item_view).parameters)
    assert parameters == ["snapshot", "legs"]


def _dds_use_case_classes() -> list[type]:
    """The class each DDS container factory constructs, read off its return annotation."""
    import inspect
    import typing

    from app.api.container import Container

    classes: list[type] = []
    for name in DDS_CONTAINER_FACTORIES:
        factory = getattr(Container, name)
        hints = typing.get_type_hints(factory)
        returned = hints["return"]
        assert inspect.isclass(returned), f"Container.{name} does not return a class"
        classes.append(returned)
    return classes


def test_the_scan_knows_every_dds_factory_the_container_has() -> None:
    """A guard on the guard: a DDS factory added to the container joins this scan or fails it."""
    import inspect

    from app.api.container import Container

    in_container = {
        name
        for name, member in inspect.getmembers(Container, inspect.isfunction)
        if not name.startswith("_")
        and member.__module__ == "app.api.container"
        and "app.application.dds" in getattr(member, "__annotations__", {}).get("return", "")
    }
    named = set(DDS_CONTAINER_FACTORIES)
    assert named >= in_container or in_container <= named, (
        f"the container has DDS factories this scan does not cover: {sorted(in_container - named)}"
    )
    assert len(named) == len(DDS_CONTAINER_FACTORIES)


@pytest.mark.parametrize("use_case", _dds_use_case_classes(), ids=lambda cls: cls.__name__)
def test_no_dds_service_is_constructed_with_a_forbidden_repository(use_case: type) -> None:
    """D3, on the constructor: what a DDS service is *handed* decides what it can read.

    The import scan above proves the module names nothing forbidden; this proves the object does
    not receive one either — the two together are what "cannot read it because they are never
    given it" means.
    """
    import inspect

    signature = inspect.signature(use_case.__init__)
    mentioned = {
        name
        for parameter in signature.parameters.values()
        for name in _annotation_names(parameter.annotation)
    }
    offenders = sorted(mentioned & FORBIDDEN_NAMES)
    assert not offenders, f"{use_case.__name__}.__init__ takes {offenders}"


#: What a DDS service may not be handed either since I3 E3a (HLD 70 §70.1 INV 3): the DDS
#: `field_specs` come from the reference pack the session recorded, never from the scenario.
SCENARIO_NAMES: frozenset[str] = frozenset(
    {"ScenarioVersion", "ScenarioRepository", "SqlAlchemyScenarioRepository", "scenarios"}
)


@pytest.mark.parametrize("use_case", _dds_use_case_classes(), ids=lambda cls: cls.__name__)
def test_no_dds_service_is_constructed_with_the_scenario(use_case: type) -> None:
    """I3 E3a: the ДДС card schema is the pack's (`reference` port + the log), so no DDS service
    receives the `ScenarioVersion` or a scenario repository to find it."""
    import inspect

    signature = inspect.signature(use_case.__init__)
    mentioned = {
        name
        for parameter in signature.parameters.values()
        for name in _annotation_names(parameter.annotation)
    }
    offenders = sorted(mentioned & SCENARIO_NAMES)
    assert not offenders, f"{use_case.__name__}.__init__ takes {offenders}"


def test_the_card_schema_step_takes_only_a_view_a_snapshot_and_a_schema() -> None:
    """`with_card_schema` (I3 E3a) adds the pack's field specs to the projection and holds
    nothing: a specification in, the same values out."""
    import inspect

    from app.application.handoff.work_item import with_card_schema

    parameters = list(inspect.signature(with_card_schema).parameters)
    assert parameters == ["view", "snapshot", "schema"]
    names = _mentioned_names(WORK_ITEM)
    assert not names & SCENARIO_NAMES


def _annotation_names(annotation: Any) -> set[str]:
    """Every identifier in a parameter annotation, however it is spelled."""
    if annotation is inspect_empty():
        return set()
    text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    if not text:
        text = str(annotation)
    return set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text))


def inspect_empty() -> Any:
    """`inspect.Parameter.empty`, imported lazily so the module top stays database-free."""
    import inspect

    return inspect.Parameter.empty


# ---------------------------------------------------------------------------------------------
# (a2) Structural — the REST projections carry no hidden-world provenance (E20-A, R1)
# ---------------------------------------------------------------------------------------------
#
# `source_world_event_id` is not a world *value*, so the JSON searches below (which hunt for the
# world's house number) never caught it. It is the id of the hidden world event that produced a
# notification or a radio message, and naming it to a trainee tells them which scripted world
# event just fired — hidden-layer provenance. The WS path already drops it for trainees
# (`application/realtime/redaction.py`, HLD 40 §215-239); the REST list paths used to hand it
# straight through. These assertions are structural — on the model fields and on the published
# contract — so they hold with no database and bite the moment a field is re-added anywhere.

#: Field names no trainee-facing REST projection of a notification or a radio message may declare.
FORBIDDEN_REST_FIELDS: frozenset[str] = frozenset({"source_world_event_id", "world_event"})

OPENAPI = BACKEND.parent / "docs" / "hld" / "openapi.yaml"

#: The trainee-facing view pairs: (application projection, wire schema), by openapi schema name.
TRAINEE_REST_VIEWS: tuple[str, ...] = ("NotificationView", "RadioMessageView")


def _trainee_rest_models() -> list[tuple[str, type]]:
    """Both layers of each trainee-facing view: the application projection and the wire model."""
    from app.api.schemas import dds as wire
    from app.application.dds import views as projections

    pairs: list[tuple[str, type]] = []
    for name in TRAINEE_REST_VIEWS:
        pairs.append((f"application/dds/views.{name}", getattr(projections, name)))
        pairs.append((f"api/schemas/dds.{name}Schema", getattr(wire, f"{name}Schema")))
    return pairs


@pytest.mark.parametrize(
    ("label", "model"),
    _trainee_rest_models(),
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_no_trainee_rest_view_declares_hidden_world_provenance(label: str, model: type) -> None:
    """INV 3 on the REST path: neither projection nor wire model declares the provenance id."""
    declared = set(model.model_fields)
    offenders = sorted(declared & FORBIDDEN_REST_FIELDS)
    assert not offenders, (
        f"{label} declares {offenders}: a trainee-facing REST view must not name the hidden "
        "world event that produced the row (SPEC §42 test 3, HLD 40 §215-239)"
    )


def test_the_published_contract_does_not_promise_hidden_world_provenance() -> None:
    """The same claim on `openapi.yaml`, which is what the frontend types are generated from."""
    import yaml

    document = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]
    for name in TRAINEE_REST_VIEWS:
        schema = schemas[name]
        offenders = sorted(set(schema["properties"]) & FORBIDDEN_REST_FIELDS)
        assert not offenders, f"openapi.yaml {name} declares {offenders}"
        assert not sorted(set(schema.get("required", ())) & FORBIDDEN_REST_FIELDS)


def test_the_projection_helpers_never_read_the_provenance_key_from_a_payload() -> None:
    """And the projection code itself does not read the key out of the event payload."""
    source = (DDS_PACKAGE / "views.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DDS_PACKAGE / "views.py"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    # Docstrings mention the name (deliberately, to explain the rule); a *key lookup* would show
    # up as a bare string constant equal to it, so only exact matches count.
    assert "source_world_event_id" not in literals


# ---------------------------------------------------------------------------------------------
# (b) Behavioural — the full 112 → DDS run
# ---------------------------------------------------------------------------------------------
#
# The API fixtures live in `tests/api/**/conftest.py` and are re-exported here by name, exactly as
# `test_inv_04_asr_never_mutates_card.py` does: `pytest_plugins` cannot register a module that is
# already loaded as a real conftest. `clean_database` is deliberately NOT re-exported — the
# structural tests above must stay database-free — and `clean_api_db` below is its explicit twin.

from tests.api import conftest as _api_fixtures  # noqa: E402
from tests.api.handoff import conftest as _handoff_fixtures  # noqa: E402
from tests.api.operator import conftest as _operator_fixtures  # noqa: E402
from tests.api.realtime import conftest as _realtime_fixtures  # noqa: E402

api_settings = _api_fixtures.api_settings
client = _api_fixtures.client
demo_version_id = _api_fixtures.demo_version_id
hasher = _api_fixtures.hasher
inference = _api_fixtures.inference
publisher = _api_fixtures.publisher
redis_client = _api_fixtures.redis_client
tokens = _api_fixtures.tokens
unit_of_work = _api_fixtures.unit_of_work
users = _api_fixtures.users

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

websocket = _realtime_fixtures.websocket

OperatorFlow = _handoff_fixtures.OperatorFlow

_TRUNCATE = text("TRUNCATE TABLE users, scenarios RESTART IDENTITY CASCADE")

#: What the world says, and what the caller (and therefore the operator) says instead — SPEC §3.
WORLD_HOUSE = "27"
CARD_HOUSE = "72"


@pytest.fixture
async def clean_api_db(migrated_engine: AsyncEngine) -> AsyncIterator[None]:
    """`tests.api.conftest.clean_database`, requested explicitly instead of autouse."""
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)
    yield
    async with migrated_engine.begin() as connection:
        await connection.execute(_TRUNCATE)


def _contains_world_value(payload: Any) -> bool:
    """Is the world's house number anywhere in this structure, in any key or value?

    `"27"` is searched as a JSON token — `":\\"27\\""` and `"\\"27\\""` — so that an unrelated
    number that merely contains the digits (an offset of 127_000 ms, say) does not false-positive
    while a real leak of the string cannot hide in a key nobody asserted on.
    """
    encoded = json.dumps(payload, ensure_ascii=False)
    return f'"{WORLD_HOUSE}"' in encoded


@pytest.mark.integration
async def test_the_scenario_really_does_hide_a_different_house_number(
    clean_api_db: None, dds_active: OperatorFlow, uow_factory: Callable[..., Any]
) -> None:
    """The premise of the whole test: world truth genuinely holds "27" for this incident.

    Without this, a test that finds no "27" on the DDS side would prove nothing at all.
    """
    async with uow_factory() as uow:
        row = (
            await uow.session.execute(
                text(
                    "SELECT w.facts FROM incident_world_states w JOIN incidents i"
                    " ON i.id = w.incident_id WHERE i.session_id = :session_id"
                ),
                {"session_id": dds_active.session_id},
            )
        ).one()
        await uow.commit()

    assert _contains_world_value(dict(row.facts)), (
        "the demo scenario's world truth must hold the house number the operator got wrong"
    )
    assert row.facts["address.house"] == WORLD_HOUSE


@pytest.mark.integration
async def test_the_dds_work_item_carries_the_operators_value_not_the_worlds(
    clean_api_db: None, dds_active: OperatorFlow
) -> None:
    """SPEC §3: DDS receives "72", and "27" appears nowhere in the payload."""
    snapshot = (await dds_active.snapshot(token=dds_active.dds_token)).json()

    work_item = snapshot["work_item"]
    assert work_item is not None
    assert work_item["card_values"]["address.house"] == CARD_HOUSE
    assert not _contains_world_value(work_item), "the world's house number reached the DDS panel"
    assert snapshot["card"] is None, "a DDS viewer never receives the live OperatorCard (D3)"
    assert not _contains_world_value(snapshot)


@pytest.mark.integration
async def test_an_omitted_field_stays_omitted_and_is_reported_as_missing(
    clean_api_db: None, dds_active: OperatorFlow
) -> None:
    """SPEC §10: "if the 112 operator omitted a critical fact, the omission propagates"."""
    work_item = (await dds_active.snapshot(token=dds_active.dds_token)).json()["work_item"]

    # `address.floor` was never sent by the trainee, and nothing invented one. It is not
    # `required_for_handoff`, so it is not even reported — it is simply, silently, absent.
    assert "address.floor" not in work_item["card_values"]
    assert not any("floor" in key for key in work_item["card_values"])
    assert "address.floor" not in work_item["missing_field_paths"]

    # `caller.phone` *is* `required_for_handoff` and was not sent either, so the gap is named —
    # and named is all it is: no value for it appears anywhere in the work item.
    assert work_item["missing_field_paths"] == ["caller.phone"]
    for path in work_item["missing_field_paths"]:
        assert path not in work_item["card_values"]


@pytest.mark.integration
async def test_no_dds_visible_event_payload_carries_the_world_value(
    clean_api_db: None, dds_active: OperatorFlow
) -> None:
    """The REST event page the DDS console reads, searched as raw JSON."""
    response = await dds_active.get("/events", token=dds_active.dds_token, params={"limit": 500})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"], "the DDS role sees at least the handoff it received"
    assert {item["event_type"] for item in body["items"]} >= {"HANDOFF_RECEIVED"}
    assert not _contains_world_value(body), "a DDS-visible event payload carries the world value"


@pytest.mark.integration
async def test_no_dds_websocket_frame_carries_the_world_value(
    clean_api_db: None,
    dds_active: OperatorFlow,
    websocket: Callable[..., Any],
    tokens: dict[str, str],
) -> None:
    """§40.4's DDS connection, replayed from zero: the whole stream, searched as raw JSON."""
    async with websocket(dds_active.session_id, token=tokens["trainee2"]) as socket:
        await socket.send_json({"type": "resume", "after_seq_no": 0})
        frames = await socket.receive_until("resume_complete")

    events = [frame for frame in frames if frame["type"] == "event"]
    assert events, "the DDS connection replays at least the handoff it received"
    assert EventType.HANDOFF_RECEIVED.value in {frame["event_type"] for frame in events}
    assert not _contains_world_value(frames), "a DDS WebSocket frame carries the world value"


@pytest.mark.integration
async def test_the_frozen_snapshot_row_itself_holds_the_operators_value(
    clean_api_db: None, dds_active: OperatorFlow, uow_factory: Callable[..., Any]
) -> None:
    """The last place a repair could have happened: the `handoff_snapshots` row on disk."""
    async with uow_factory() as uow:
        rows = [
            dict(row._mapping)
            for row in (await uow.session.execute(text("SELECT * FROM handoff_snapshots"))).all()
        ]
        await uow.commit()

    assert len(rows) == 1
    assert rows[0]["card_values"]["address.house"] == CARD_HOUSE
    assert "address.floor" not in rows[0]["card_values"]
    assert not _contains_world_value(rows[0]["card_values"])


# ---------------------------------------------------------------------------------------------
# (c) Behavioural — the DDS side in motion (E9-B)
# ---------------------------------------------------------------------------------------------
#
# The tests above prove the *handed-over* work item is clean. These prove the surfaces the DDS
# trainee actually works on stay clean once the stage runs: the stage view every command returns,
# the resource board, the notification list and the radio log. The search is the same — the raw
# JSON, for the world's house number — because a leak in a key nobody asserted on is still a leak.


async def _dds_cycle(flow: OperatorFlow, clock: Any) -> list[Any]:
    """Acknowledge, select and dispatch a unit, then run the clock past the first world event."""
    bodies: list[Any] = []
    for suffix in ("/dds/acknowledge", "/dds/resources/selection/open"):
        response = await flow.post(suffix, token=flow.dds_token)
        assert response.status_code == 200, response.text
        bodies.append(response.json())

    board = (await flow.get("/dds/resources", token=flow.dds_token)).json()
    bodies.append(board)
    engine = next(item for item in board["items"] if item["callsign"] == "АЦ-1")
    selected = await flow.post(
        "/dds/resources/select", token=flow.dds_token, json={"resource_id": engine["resource_id"]}
    )
    assert selected.status_code == 200, selected.text
    bodies.append(selected.json())

    dispatched = await flow.post(
        "/dds/resources/dispatch", token=flow.dds_token, json={"note_ru": None}
    )
    assert dispatched.status_code == 200, dispatched.text
    bodies.append(dispatched.json())

    detail = (await flow.get("", token=flow.instructor_token)).json()
    clock.advance_ms(190_000 - int(detail["monotonic_offset_ms"]))
    await flow.container.runner.tick_now(SessionId(flow.session_id))
    return bodies


@pytest.mark.integration
async def test_no_dds_command_response_carries_the_world_value(
    clean_api_db: None, dds_active: OperatorFlow, clock: Any
) -> None:
    """Every `DdsStageView` a command returns embeds the work item — and only the work item."""
    bodies = await _dds_cycle(dds_active, clock)

    for body in bodies:
        assert not _contains_world_value(body), "a DDS command response carries the world value"


@pytest.mark.integration
async def test_neither_notifications_nor_radio_carry_the_world_value(
    clean_api_db: None, dds_active: OperatorFlow, clock: Any
) -> None:
    """SPEC §12's channels are world-*event* channels, not world-*truth* channels."""
    await _dds_cycle(dds_active, clock)

    notifications = await dds_active.get("/dds/notifications", token=dds_active.dds_token)
    radio = await dds_active.get("/dds/radio-messages", token=dds_active.dds_token)

    assert notifications.status_code == 200, notifications.text
    assert radio.status_code == 200, radio.text
    assert notifications.json()["items"], "the run produced at least one DDS notification"
    assert not _contains_world_value(notifications.json())
    assert not _contains_world_value(radio.json())


@pytest.mark.integration
async def test_the_running_dds_stage_still_shows_the_operators_value(
    clean_api_db: None, dds_active: OperatorFlow, clock: Any
) -> None:
    """The positive half: "72" is there, in the work item the console keeps re-reading."""
    await _dds_cycle(dds_active, clock)

    item = (await dds_active.get("/dds/work-item", token=dds_active.dds_token)).json()

    assert item["card_values"]["address.house"] == CARD_HOUSE
    assert item["state"] in ("DISPATCHED", "EN_ROUTE", "ARRIVED")
