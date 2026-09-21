"""§10.12's decision table agrees with `evaluate_fact_access` — parsed, never retyped.

The same pattern as `backend/tests/unit/domain/roles/test_dds_tables_match_the_hld.py`: the
nine-row table of `docs/hld/10-domain-model.md` §10.12 is read at test time, every row is turned
into the smallest input that satisfies its cells, and the gate's `(outcome, reason)` for that
input is compared with the row's own two columns. Nothing below restates the table. Editing the
document without editing the gate fails this test, and the reverse fails it too.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.domain.enums import DisclosurePolicy, GateOutcome, GateReason, KnowledgeState
from app.domain.facts.definitions import AvailableAfter, FactDefinition
from app.domain.facts.gate import FactRequest, GateConditionContext, evaluate_fact_access

from tests.unit.domain.facts._support import belief, definition, definitions

DOMAIN_MODEL_PATH = Path(__file__).resolve().parents[5] / "docs" / "hld" / "10-domain-model.md"

_BACKTICKED = re.compile(r"`([A-Za-z_0-9]+)`")

#: The `available_after` the gate is given when the row's cell says "unmet": far in the future,
#: evaluated at t=0. "met or absent" and "any" both get no `available_after` at all.
UNMET_AFTER = AvailableAfter(sim_time_ms=10_000_000)


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
        if cells[0].startswith(":--") or cells[0] == "#":
            continue
        rows.append(cells)
    return rows


DECISION_ROWS = _rows(_section("### Decision table"), 10)


def test_the_parser_saw_all_nine_rows() -> None:
    """A guard on the guard: a parser that matched nothing would pass every test below."""
    assert [cells[0] for cells in DECISION_ROWS] == [str(number) for number in range(1, 10)]


def _policies(cell: str) -> tuple[DisclosurePolicy, ...]:
    """The policies a row's policy cell covers."""
    named = [DisclosurePolicy(name) for name in _BACKTICKED.findall(cell)]
    if named:
        return tuple(named)
    # "any other" = every policy but `NEVER_DISCLOSE`, which row 2 already caught.
    return tuple(
        policy for policy in DisclosurePolicy if policy is not DisclosurePolicy.NEVER_DISCLOSE
    )


def _knowledges(cell: str) -> tuple[KnowledgeState, ...]:
    """The knowledge states a row's knowledge cell covers."""
    named = [KnowledgeState(name) for name in _BACKTICKED.findall(cell)]
    if named:
        return tuple(named)
    if "row 4" in cell:
        return _knowledges("`KNOWN`/`INCORRECT_BELIEF`/`UNCERTAIN`")
    # "any" — row 2 is the only one, and it must hold for every state.
    return tuple(KnowledgeState)


def _booleans(cell: str) -> tuple[bool, ...]:
    """A yes/no/any cell as the values it covers."""
    stripped = cell.replace("*", "").strip().lower()
    if stripped == "yes":
        return (True,)
    if stripped == "no":
        return (False,)
    return (False, True)


def _availables(cell: str) -> tuple[bool, ...]:
    """The `available_after` cell as "is it met" values."""
    stripped = cell.replace("*", "").strip().lower()
    if stripped == "unmet":
        return (False,)
    if stripped.startswith("met"):
        return (True,)
    return (False, True)


def _case_ids() -> list[tuple[str, DisclosurePolicy, KnowledgeState, bool, bool, bool, str, str]]:
    """Every (row, policy, knowledge, available, explicit, revealed) the document describes."""
    cases = []
    for cells in DECISION_ROWS:
        if cells[1].strip() == "no":  # row 1: the fact is not defined at all
            continue
        for policy in _policies(cells[2]):
            for knowledge in _knowledges(cells[3]):
                for available in _availables(cells[4]):
                    for explicit in _booleans(cells[5]):
                        for revealed in _booleans(cells[6]):
                            cases.append(
                                (
                                    cells[0],
                                    policy,
                                    knowledge,
                                    available,
                                    explicit,
                                    revealed,
                                    _BACKTICKED.findall(cells[7])[0],
                                    _BACKTICKED.findall(cells[8])[0],
                                )
                            )
    return cases


def _first_matching_row(
    policy: DisclosurePolicy,
    knowledge: KnowledgeState,
    available: bool,
    explicit: bool,
    revealed: bool,
) -> str:
    """The row number the document's own top-down, first-match rule selects for this input."""
    for cells in DECISION_ROWS:
        if cells[1].strip() == "no":
            continue
        if policy not in _policies(cells[2]):
            continue
        if knowledge not in _knowledges(cells[3]):
            continue
        if available not in _availables(cells[4]):
            continue
        if explicit not in _booleans(cells[5]):
            continue
        if revealed not in _booleans(cells[6]):
            continue
        return cells[0]
    raise AssertionError("the decision table has a hole")


def _defs(
    policy: DisclosurePolicy, knowledge: KnowledgeState, available: bool
) -> dict[str, FactDefinition]:
    return definitions(
        definition(
            "a",
            policy=policy,
            knowledge=knowledge,
            caller_value=None if knowledge is KnowledgeState.UNKNOWN else "значение",
            available_after=None if available else UNMET_AFTER,
        )
    )


@pytest.mark.parametrize(
    ("row", "policy", "knowledge", "available", "explicit", "revealed", "outcome", "reason"),
    _case_ids(),
    ids=lambda value: str(getattr(value, "value", value)),
)
def test_every_documented_cell_matches_the_gate(
    row: str,
    policy: DisclosurePolicy,
    knowledge: KnowledgeState,
    available: bool,
    explicit: bool,
    revealed: bool,
    outcome: str,
    reason: str,
) -> None:
    """One assertion per (row × policy × knowledge × availability × explicit × revealed) cell."""
    if _first_matching_row(policy, knowledge, available, explicit, revealed) != row:
        pytest.skip("an earlier row of the document claims this input")

    defs = _defs(policy, knowledge, available)
    revealed_ids = frozenset({"a"}) if revealed else frozenset()

    _package, decisions = evaluate_fact_access(
        [FactRequest(fact_id="a", explicit=explicit)],
        defs,
        belief(defs, revealed=revealed_ids),
        revealed_ids,
        0,
        GateConditionContext(),
    )

    assert decisions[0].outcome is GateOutcome(outcome), f"row {row}"
    assert decisions[0].reason is GateReason(reason), f"row {row}"


def test_row_1_is_the_undefined_fact_row() -> None:
    """Row 1's `fact_id known` cell is the only "no", and it needs no definition to test."""
    row = DECISION_ROWS[0]
    assert row[1].strip() == "no"

    _package, decisions = evaluate_fact_access(
        [FactRequest(fact_id="absent", explicit=True)],
        {},
        belief({}),
        frozenset(),
        0,
        GateConditionContext(),
    )

    assert decisions[0].outcome is GateOutcome(_BACKTICKED.findall(row[7])[0])
    assert decisions[0].reason is GateReason(_BACKTICKED.findall(row[8])[0])


def test_every_documented_outcome_and_reason_is_reachable() -> None:
    """Every `GateOutcome`/`GateReason` the table names exists in the code enums."""
    outcomes = {GateOutcome(_BACKTICKED.findall(cells[7])[0]) for cells in DECISION_ROWS}
    reasons = {GateReason(_BACKTICKED.findall(cells[8])[0]) for cells in DECISION_ROWS}

    assert outcomes | {GateOutcome.ALLOWED_SPONTANEOUS} == set(GateOutcome)
    assert reasons == set(GateReason)
