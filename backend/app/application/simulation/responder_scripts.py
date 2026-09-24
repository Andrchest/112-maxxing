"""`ScenarioResponderScripts` — the scripted responders of a session's scenario, for stage
automation only (I3 E5b, HLD 70 §70.1 INV 3, §70.4.5).

`expected_response.responders` is scenario data. INV 3 says the DDS side never reads the scenario:
DDS commands and reads are constructed without a scenario repository, and so is the DDS stage
automation. The runner side is where the scenario is read (`TickSession.resolution_condition_met`
reads `resolution_condition` the same way), so this probe lives here and the composition root hands
it to `app.application.dds.stage_automation.DdsStageAutomation` as a callable — the automation
learns the script and nothing else of the scenario, and no DDS command can reach it.
"""

from __future__ import annotations

from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import SessionId
from app.domain.dds.responders import ScriptedResponders
from app.domain.scenario.version import ScenarioVersion

__all__ = ["ScenarioResponderScripts"]


class ScenarioResponderScripts:
    """`session_id → expected_response.responders` of the session's scenario version."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, session_id: SessionId) -> ScriptedResponders | None:
        """The session's `responders` (`DEFAULT` or a script per service); `None` when the scenario
        declares none (a picker-only scenario, rule R36) or the session is gone."""
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            document = (
                None
                if session is None
                else await uow.scenarios.get_version_document(session.scenario_version_id)
            )
            await uow.commit()
        if document is None:
            return None
        return ScenarioVersion.model_validate(dict(document)).expected_response.responders
