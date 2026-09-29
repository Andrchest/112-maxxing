"""`ScenarioResponderScripts` — the scripted responders of a session's scenario, for stage
automation only (I3 E5b, HLD 70 §70.1 INV 3, §70.4.5).

`expected_response.responders` is scenario data. INV 3 says the DDS side never reads the scenario:
DDS commands and reads are constructed without a scenario repository, and so is the DDS stage
automation. The runner side is where the scenario is read (`TickSession.resolution_condition_met`
reads `resolution_condition` the same way), so this probe lives here and the composition root hands
it to `app.application.dds.stage_automation.DdsStageAutomation` as a callable — the automation
learns the script and nothing else of the scenario, and no DDS command can reach it.

`persona_override` (I3 E6c, HLD 80 §80.4.1, R42) is the one narrow answer the ДДС phone needs from
the same key: the persona id a scenario names for one service, which `startDdsCall` records on
`DDS_CALL_STARTED` (P4). It answers a persona id and nothing else — never a step of the script.

**Cached per session (I7 E48).** Stage automation asks on every tick of every ACTIVE session, and
each answer cost a Unit of Work plus a full `ScenarioVersion` validation of the document. The
answer cannot change for the life of a session — its `scenario_version_id` is fixed at creation
and a version's content is immutable (D4) — so it is kept in a process-wide map, bounded by
`_CACHE_LIMIT` (the oldest entry is dropped first). A session that is not found is not cached.
"""

from __future__ import annotations

from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import SessionId
from app.domain.dds.responders import ScriptedResponders, persona_override_for
from app.domain.scenario.version import ScenarioVersion

__all__ = ["ScenarioResponderScripts"]

#: Sessions whose answer is kept (a classroom runs tens of sessions at once; this is far above).
_CACHE_LIMIT = 4096
_cache: dict[SessionId, ScriptedResponders | None] = {}


class ScenarioResponderScripts:
    """`session_id → expected_response.responders` of the session's scenario version."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, session_id: SessionId) -> ScriptedResponders | None:
        """The session's `responders` (`DEFAULT` or a script per service); `None` when the scenario
        declares none (a picker-only scenario, rule R36) or the session is gone."""
        if session_id in _cache:
            return _cache[session_id]
        async with self._unit_of_work() as uow:
            session = await uow.sessions.get(session_id)
            document = (
                None
                if session is None
                else await uow.scenarios.get_version_document(session.scenario_version_id)
            )
            await uow.commit()
        if session is None:
            return None
        responders = (
            None
            if document is None
            else ScenarioVersion.model_validate(dict(document)).expected_response.responders
        )
        if len(_cache) >= _CACHE_LIMIT:
            del _cache[next(iter(_cache))]
        _cache[session_id] = responders
        return responders

    async def persona_override(self, session_id: SessionId, service_id: str) -> str | None:
        """The scenario's persona override for one service (R42), or `None`."""
        return persona_override_for(await self(session_id), service_id)
