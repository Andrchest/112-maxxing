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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.domain.dds.resources import (
    RESOURCE_STATUS_TRANSITIONS,
    SELECTION_OPEN_STATES,
)
from app.domain.enums import ActorType, DDSStageState, ResourceStatus
from app.domain.roles.dds import DDSModule

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


def _documented_actions() -> dict[DDSStageState, tuple[str, ...]]:
    """`state -> the action ids §10.9 lists for it`, in the document's order."""
    table: dict[DDSStageState, tuple[str, ...]] = {}
    for cells in _rows(_DDS_MODULE_SECTION, 2):
        names = _BACKTICKED.findall(cells[0])
        if not names or names[0] not in DDSStageState.__members__:
            continue
        state = DDSStageState(names[0])
        actions = tuple(
            _BACKTICKED.findall(part)[0]
            for part in cells[1].split(";")
            if _BACKTICKED.findall(part)
        )
        table[state] = actions
    return table


DOCUMENTED_ACTIONS = _documented_actions()


def test_the_parser_saw_every_dds_stage_state() -> None:
    """A guard on the guard: §10.9's table covers all nine states, `CLOSED` with none."""
    assert set(DOCUMENTED_ACTIONS) == set(DDSStageState)
    assert DOCUMENTED_ACTIONS[DDSStageState.CLOSED] == ()


@pytest.mark.parametrize("state", list(DDSStageState))
def test_available_actions_match_the_documented_table(state: DDSStageState) -> None:
    """`DDSModule.available_actions(state)` is §10.9's row, ids and order."""
    actual = tuple(action.action_id for action in DDSModule().available_actions(state))
    assert actual == DOCUMENTED_ACTIONS[state]


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
