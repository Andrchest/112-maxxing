"""Every SPEC §7 state is reachable from its machine's initial state.

Pure graph reachability over the table's `(source, trigger) -> target` edges — no guard/actor
context is needed to ask "is there *a* path", only whether the table connects the states.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.dds.resources import RESOURCE_STATUS_TRANSITIONS
from app.domain.enums import DDSStageState, Operator112StageState, ResourceStatus, SessionState
from app.domain.session.transitions import (
    DDS_TRANSITIONS,
    OPERATOR_112_TRANSITIONS,
    SESSION_TRANSITIONS,
)


def _reachable_from(table: Mapping[tuple[object, str], object], initial: object) -> set[object]:
    seen = {initial}
    frontier = [initial]
    while frontier:
        state = frontier.pop()
        for (source, _trigger), transition in table.items():
            if source == state:
                target = transition.target  # type: ignore[attr-defined]
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
    return seen


def test_every_session_state_reachable_from_created() -> None:
    reachable = _reachable_from(SESSION_TRANSITIONS, SessionState.CREATED)
    assert reachable == set(SessionState)


def test_every_operator_112_stage_state_reachable_from_waiting_for_call() -> None:
    reachable = _reachable_from(OPERATOR_112_TRANSITIONS, Operator112StageState.WAITING_FOR_CALL)
    assert reachable == set(Operator112StageState)


def test_every_dds_stage_state_reachable_from_received() -> None:
    reachable = _reachable_from(DDS_TRANSITIONS, DDSStageState.RECEIVED)
    assert reachable == set(DDSStageState)


def test_every_resource_status_reachable_from_available() -> None:
    """Not a SPEC §7 machine, but the same reachability property is worth pinning here too."""
    reachable = _reachable_from(RESOURCE_STATUS_TRANSITIONS, ResourceStatus.AVAILABLE)
    assert reachable == set(ResourceStatus)
