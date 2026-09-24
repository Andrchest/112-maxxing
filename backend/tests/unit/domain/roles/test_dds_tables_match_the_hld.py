"""The two DDS tables of `10-domain-model.md` agree with the code — parsed, never retyped.

E9 repaired `dispatch_additional`, which was unreachable as the HLD was originally written, by
editing two tables: §10.7's `RESOURCE_STATUS_TRANSITIONS` (the `select` / `dispatch` guard cells)
and §10.9's `DDSModule.available_actions` (`select_resource` / `deselect_resource` in `EN_ROUTE`,
`ARRIVED` and `WORKING`). The two halves of that repair — the document and the code — landed in
two different tasks, and for a while they disagreed with nothing to notice it.

This test is what makes that drift impossible to repeat. It reads the document at test time and
compares it with `app.domain.dds.resources` and `app.domain.roles.dds`:

* every `(source, trigger) -> target` row of §10.7, and who may fire it;
* the assignment states the two trainee-fired rows name in their guard column, against
  `SELECTION_OPEN_STATES`;
* every state's `available_actions` ids of §10.9, in the document's order.

Nothing here restates either table. Changing the document without changing the code fails this
test, and changing the code without changing the document fails it too.

I3 E5a (HLD 70 §70.4.4) taught it two more tables: §10.9 is **variant-labelled** now — the picker
table under "**`dds_mode: RESOURCE_PICKER`**" and the memo table under "**`dds_mode:
MEMO_STATUSES`**", each compared with `DDSModule.available_actions(state, variants=…)` of its mode —
and §10.7's new `SERVICE_RESPONSE_TRANSITIONS` table is compared row for row with
`app.domain.dds.response`, like the resource table above it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.domain.dds.resources import (
    RESOURCE_STATUS_TRANSITIONS,
    SELECTION_OPEN_STATES,
)
from app.domain.dds.response import SERVICE_RESPONSE_TRANSITIONS, ServiceResponseStatus
from app.domain.enums import ActorType, DDSStageState, ResourceStatus
from app.domain.roles.dds import DDSModule
from app.domain.session.variants import (
    CardSource,
    DdsBrigadeCall,
    DdsCardCheck,
    DdsMode,
    SessionVariants,
)

DOMAIN_MODEL_PATH = Path(__file__).resolve().parents[5] / "docs" / "hld" / "10-domain-model.md"

_BACKTICKED = re.compile(r"`([A-Za-z_0-9]+)`")


def _section(heading: str) -> str:
    """The markdown between `heading` and the next heading of the same or a higher level."""
    text = DOMAIN_MODEL_PATH.read_text(encoding="utf-8")
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(r"^#{1,3} ", rest, re.MULTILINE)
    return rest if end is None else rest[: end.start()]


def _rows(section: str, columns: int) -> list[list[str]]:
    """Every data row of the section's first markdown table, as stripped cells."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        if len(cells) != columns:
            continue
        if cells[0].startswith(":--") or cells[0] in ("From", "State"):
            continue
        rows.append(cells)
    return rows


# ---------------------------------------------------------------------------------------------
# §10.7 — RESOURCE_STATUS_TRANSITIONS
# ---------------------------------------------------------------------------------------------

_TRANSITIONS_SECTION = _section("### Resource status state machine")


def _documented_transitions() -> dict[tuple[ResourceStatus, str], tuple[ResourceStatus, str]]:
    """`(source, trigger) -> (target, who)`, read off §10.7's five-column table."""
    table: dict[tuple[ResourceStatus, str], tuple[ResourceStatus, str]] = {}
    for cells in _rows(_TRANSITIONS_SECTION, 5):
        sources = _BACKTICKED.findall(cells[0])
        trigger = _BACKTICKED.findall(cells[1])[0]
        target = _BACKTICKED.findall(cells[2])[0]
        who = "TRAINEE" if "TRAINEE" in cells[3] else "SIMULATION"
        for source in sources:
            table[(ResourceStatus(source), trigger)] = (ResourceStatus(target), who)
    return table


DOCUMENTED_TRANSITIONS = _documented_transitions()


def test_the_parser_saw_the_whole_transition_table() -> None:
    """A guard on the guard: a parser that matched nothing would pass every test below."""
    assert len(DOCUMENTED_TRANSITIONS) >= 12
    assert (ResourceStatus.AVAILABLE, "select") in DOCUMENTED_TRANSITIONS


def test_the_code_has_exactly_the_documented_rows() -> None:
    """§10.7's table is `RESOURCE_STATUS_TRANSITIONS`, row for row."""
    assert set(RESOURCE_STATUS_TRANSITIONS) == set(DOCUMENTED_TRANSITIONS)


@pytest.mark.parametrize("key", sorted(DOCUMENTED_TRANSITIONS, key=lambda item: (item[0], item[1])))
def test_each_row_moves_where_the_document_says_and_is_fired_by_whom_it_says(
    key: tuple[ResourceStatus, str],
) -> None:
    """Target and firing actor, per row."""
    target, who = DOCUMENTED_TRANSITIONS[key]
    transition = RESOURCE_STATUS_TRANSITIONS[key]
    assert transition.target is target
    expected_actor = ActorType.TRAINEE if who == "TRAINEE" else ActorType.SIMULATION
    assert transition.allowed_actors == frozenset({expected_actor})


@pytest.mark.parametrize("trigger", ["select", "dispatch"])
def test_the_widened_guard_cells_name_exactly_the_code_s_selection_states(trigger: str) -> None:
    """The E9 repair: §10.7's two trainee guard cells and `SELECTION_OPEN_STATES` agree.

    The guard column is prose, so what is compared is the set of `DDSStageState` names it puts in
    backticks — which is precisely the list the repair widened.
    """
    for cells in _rows(_TRANSITIONS_SECTION, 5):
        if _BACKTICKED.findall(cells[1])[0] != trigger or "TRAINEE" not in cells[3]:
            continue
        named = {
            DDSStageState(name)
            for name in _BACKTICKED.findall(cells[4])
            if name in DDSStageState.__members__
        }
        assert named == SELECTION_OPEN_STATES, (
            f"§10.7's `{trigger}` guard names {sorted(state.value for state in named)}"
        )
        return
    raise AssertionError(f"§10.7 has no TRAINEE-fired `{trigger}` row")


# ---------------------------------------------------------------------------------------------
# §10.9 — DDSModule.available_actions
# ---------------------------------------------------------------------------------------------

_DDS_MODULE_SECTION = _section("### `DDSModule`")
_MEMO_LABEL = "**`dds_mode: MEMO_STATUSES`**"
_PICKER_LABEL = "**`dds_mode: RESOURCE_PICKER`**"


def _variant_part(mode: DdsMode) -> str:
    """The part of §10.9's `DDSModule` section that holds `mode`'s table (I3 E5a)."""
    assert _PICKER_LABEL in _DDS_MODULE_SECTION and _MEMO_LABEL in _DDS_MODULE_SECTION
    picker, memo = _DDS_MODULE_SECTION.split(_MEMO_LABEL, 1)
    return memo if mode is DdsMode.MEMO_STATUSES else picker


def _variants(mode: DdsMode, card_check: DdsCardCheck = DdsCardCheck.OFF) -> SessionVariants:
    return SessionVariants(
        card_source=CardSource.GENERATED_CARD,
        dds_mode=mode,
        dds_card_check=card_check,
        dds_brigade_call=DdsBrigadeCall.OFF,
    )


_CARD_CHECK_ONLY = "only `dds_card_check: ON`"
"""The qualifier §10.9's memo table puts on an action offered only under card check `ON` (E5b)."""


def _documented_actions(
    mode: DdsMode = DdsMode.RESOURCE_PICKER, card_check: DdsCardCheck = DdsCardCheck.OFF
) -> dict[DDSStageState, tuple[str, ...]]:
    """`state -> the action ids §10.9 lists for it` in `mode`'s table, in the document's order.

    An action qualified "only `dds_card_check: ON`" is listed only for `card_check` `ON`."""
    table: dict[DDSStageState, tuple[str, ...]] = {}
    for cells in _rows(_variant_part(mode), 2):
        names = _BACKTICKED.findall(cells[0])
        if not names or names[0] not in DDSStageState.__members__:
            continue
        state = DDSStageState(names[0])
        actions = tuple(
            _BACKTICKED.findall(part)[0]
            for part in cells[1].split(";")
            if _BACKTICKED.findall(part)
            and (card_check is DdsCardCheck.ON or _CARD_CHECK_ONLY not in part)
        )
        table[state] = actions
    return table


DOCUMENTED_ACTIONS = _documented_actions()
DOCUMENTED_MEMO_ACTIONS = _documented_actions(DdsMode.MEMO_STATUSES)
DOCUMENTED_MEMO_CARD_CHECK_ACTIONS = _documented_actions(DdsMode.MEMO_STATUSES, DdsCardCheck.ON)
DOCUMENTED_PICKER_CARD_CHECK_ACTIONS = _documented_actions(DdsMode.RESOURCE_PICKER, DdsCardCheck.ON)


def test_the_parser_saw_every_dds_stage_state() -> None:
    """A guard on the guard: §10.9's table covers all nine states, `CLOSED` with none."""
    assert set(DOCUMENTED_ACTIONS) == set(DDSStageState)
    assert DOCUMENTED_ACTIONS[DDSStageState.CLOSED] == ()


@pytest.mark.parametrize("state", list(DDSStageState))
def test_available_actions_match_the_documented_table(state: DDSStageState) -> None:
    """`DDSModule.available_actions(state)` is §10.9's row, ids and order."""
    actual = tuple(action.action_id for action in DDSModule().available_actions(state))
    assert actual == DOCUMENTED_ACTIONS[state]


@pytest.mark.parametrize("state", list(DDSStageState))
def test_picker_variant_is_the_picker_table(state: DDSStageState) -> None:
    """`variants` with `RESOURCE_PICKER` answers exactly what `variants=None` does."""
    actual = DDSModule().available_actions(state, variants=_variants(DdsMode.RESOURCE_PICKER))
    assert tuple(action.action_id for action in actual) == DOCUMENTED_ACTIONS[state]


def test_the_parser_saw_every_state_of_the_memo_table() -> None:
    """A guard on the guard for the variant-labelled memo table (I3 E5a)."""
    assert set(DOCUMENTED_MEMO_ACTIONS) == set(DDSStageState)
    assert "set_service_status" in DOCUMENTED_MEMO_ACTIONS[DDSStageState.ACKNOWLEDGED]


@pytest.mark.parametrize("state", list(DDSStageState))
def test_memo_available_actions_match_the_documented_table(state: DDSStageState) -> None:
    """`DDSModule.available_actions(state, variants=memo)` is §10.9's memo row (HLD 70 §70.4.4)."""
    actual = DDSModule().available_actions(state, variants=_variants(DdsMode.MEMO_STATUSES))
    assert tuple(action.action_id for action in actual) == DOCUMENTED_MEMO_ACTIONS[state]


@pytest.mark.parametrize("state", list(DDSStageState))
def test_memo_card_check_actions_match_the_documented_table(state: DDSStageState) -> None:
    """Under `dds_card_check: ON` the memo row also lists `flag_card_issue` (I3 E5b, C1)."""
    variants = _variants(DdsMode.MEMO_STATUSES, DdsCardCheck.ON)
    actual = DDSModule().available_actions(state, variants=variants)
    assert tuple(action.action_id for action in actual) == DOCUMENTED_MEMO_CARD_CHECK_ACTIONS[state]


def test_flag_card_issue_is_documented_for_card_check_on_only() -> None:
    """A guard on the guard: the qualifier is parsed, and only `ACKNOWLEDGED` carries it."""
    on = DOCUMENTED_MEMO_CARD_CHECK_ACTIONS[DDSStageState.ACKNOWLEDGED]
    assert "flag_card_issue" in on
    assert "flag_card_issue" not in DOCUMENTED_MEMO_ACTIONS[DDSStageState.ACKNOWLEDGED]
    others = [actions for state, actions in DOCUMENTED_MEMO_CARD_CHECK_ACTIONS.items()]
    assert sum("flag_card_issue" in actions for actions in others) == 1
    for actions in DOCUMENTED_ACTIONS.values():
        assert "flag_card_issue" not in actions


@pytest.mark.parametrize("state", list(DDSStageState))
def test_picker_card_check_actions_match_the_documented_table(state: DDSStageState) -> None:
    """Under `dds_card_check: ON` the picker rows from `ACKNOWLEDGED` to `RESOLVED` also list
    `flag_card_issue` (I3 E5b, §70.11: card check is supported in both modes)."""
    variants = _variants(DdsMode.RESOURCE_PICKER, DdsCardCheck.ON)
    actual = DDSModule().available_actions(state, variants=variants)
    documented = DOCUMENTED_PICKER_CARD_CHECK_ACTIONS[state]
    assert tuple(action.action_id for action in actual) == documented
    flagged = state not in (DDSStageState.RECEIVED, DDSStageState.CLOSED)
    assert ("flag_card_issue" in documented) is flagged


def test_no_resource_action_is_offered_in_memo_mode() -> None:
    """§70.4.4: `select_resource`, `dispatch`, … never appear in the memo table."""
    resource_actions = {
        "open_resource_selection",
        "select_resource",
        "deselect_resource",
        "dispatch",
        "dispatch_additional",
        "back_to_acknowledged",
    }
    for actions in DOCUMENTED_MEMO_ACTIONS.values():
        assert not resource_actions & set(actions)


# ---------------------------------------------------------------------------------------------
# §10.7 — SERVICE_RESPONSE_TRANSITIONS (I3 E5a)
# ---------------------------------------------------------------------------------------------

_RESPONSE_SECTION = _section("### Service response status machine")


def _documented_response_rows() -> dict[tuple[ServiceResponseStatus, str], tuple[str, str, str]]:
    """`(source, trigger) -> (target, who, guard)`, read off the §10.7 five-column table."""
    table: dict[tuple[ServiceResponseStatus, str], tuple[str, str, str]] = {}
    for cells in _rows(_RESPONSE_SECTION, 5):
        sources = _BACKTICKED.findall(cells[0])
        trigger = _BACKTICKED.findall(cells[1])[0]
        target = _BACKTICKED.findall(cells[2])[0]
        guards = [name for name in _BACKTICKED.findall(cells[4]) if name.startswith("guard_")]
        for source in sources:
            table[(ServiceResponseStatus(source), trigger)] = (
                target,
                cells[3],
                guards[0] if guards else "",
            )
    return table


DOCUMENTED_RESPONSE_ROWS = _documented_response_rows()


def test_the_parser_saw_the_whole_response_table() -> None:
    assert len(DOCUMENTED_RESPONSE_ROWS) == len(SERVICE_RESPONSE_TRANSITIONS) >= 15


@pytest.mark.parametrize(
    "key", sorted(DOCUMENTED_RESPONSE_ROWS, key=lambda item: (item[0].value, item[1]))
)
def test_each_response_row_matches_the_document(key: tuple[ServiceResponseStatus, str]) -> None:
    """Target, firing actors and guard name, per row."""
    target, who, guard = DOCUMENTED_RESPONSE_ROWS[key]
    row = SERVICE_RESPONSE_TRANSITIONS[key]
    assert row.target is ServiceResponseStatus(target)
    expected = {actor for actor in ActorType if actor.value in who}
    assert row.allowed_actors == expected
    assert (row.guard_name or "") == guard


def test_select_is_available_wherever_dispatch_additional_is() -> None:
    """The point of the E9 repair, asserted directly rather than through the tables.

    `dispatch_additional`'s guard needs a `SELECTED` unit, so a state that offers it and does not
    offer `select_resource` is a state the trigger can never fire from.
    """
    module = DDSModule()
    for state in DDSStageState:
        ids = {action.action_id for action in module.available_actions(state)}
        if "dispatch_additional" in ids:
            assert "select_resource" in ids, f"{state.value} offers no way to select a unit"
            assert state in SELECTION_OPEN_STATES
