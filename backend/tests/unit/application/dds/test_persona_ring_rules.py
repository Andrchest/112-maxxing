"""A persona's `busy` / `no_answer` flags and the INBOUND ring timeout (I3 E6c, HLD
`80-telephony.md` §80.3.2, §80.4.1; REQ-5325 «телефон не работает либо не отвечают»).

`busy` ends the call at `ring` (`DDS_CALL_ENDED {reason: BUSY}`); `no_answer` lets it ring
`ring_timeout_ms` and end `NO_ANSWER`; an INBOUND call the trainee never answers rings out the same
way. Pure-ish: a recording `dds_calls` stand-in, no database.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.application.dds.dds_call_flow import AdvanceDdsCalls, ring_now
from app.application.testing.fakes import FakeCallTransportStatus, FakeClock
from app.domain.common.actors import ActorRef
from app.domain.common.ids import AssignmentId, SessionId, UserId
from app.domain.dds.call import (
    CallEndpoint,
    CallSelectionReason,
    DdsCall,
    DdsCallDirection,
    DdsCallKind,
    DdsCallState,
    start_call,
)
from app.domain.dds.personas import Persona, PersonaApplies, PersonaCatalog, PersonaGender
from app.domain.enums import ActorType
from app.domain.routing.catalog import LEGACY_REFERENCE, ReferenceCatalog

SESSION = SessionId(uuid.UUID("00000000-0000-4000-8000-0000000005e5"))
TRAINEE = UserId(uuid.UUID("00000000-0000-4000-8000-00000000a001"))


class _Calls:
    def __init__(self) -> None:
        self.saved: list[DdsCall] = []

    async def save(self, call: DdsCall) -> None:
        self.saved.append(call)


class _Uow:
    def __init__(self) -> None:
        self.dds_calls = _Calls()


def persona(**flags: bool) -> Persona:
    return Persona(
        id="HEAD",
        applies=PersonaApplies(code="101"),
        title_ru="Начальник караула",
        gender=PersonaGender.MALE,
        voice_id="ru_male_adult_01",
        greeting_ru="Слушаю.",
        **flags,
    )


class _Reference:
    """A `ReferencePort` whose one pack (`legacy-r1`, what an empty log reads) has the persona."""

    def __init__(self, head: Persona) -> None:
        legacy = LEGACY_REFERENCE.pack("legacy-r1")
        services = LEGACY_REFERENCE.services("legacy-r1")
        assert legacy is not None and services is not None
        self._catalog = ReferenceCatalog(
            packs=(legacy.model_copy(update={"personas": "p"}),),
            service_catalogs=(services,),
            persona_catalogs=(PersonaCatalog(catalog_id="p", personas=(head,)),),
        )

    def catalog(self) -> ReferenceCatalog:
        return self._catalog


def head_call(direction: DdsCallDirection = DdsCallDirection.OUTBOUND) -> DdsCall:
    actor = (
        ActorRef(actor_type=ActorType.TRAINEE, actor_id=TRAINEE)
        if direction is DdsCallDirection.OUTBOUND
        else ActorRef(actor_type=ActorType.SIMULATION)
    )
    call, _event = start_call(
        call_id=uuid.uuid4(),
        session_id=SESSION,
        kind=DdsCallKind.SERVICE_HEAD,
        direction=direction,
        dialed="101",
        endpoint=CallEndpoint.BROWSER,
        actor=actor,
        now_ms=1_000,
        selection_reason=(
            CallSelectionReason.BROWSER_BUTTON
            if direction is DdsCallDirection.OUTBOUND
            else CallSelectionReason.INBOUND_SCRIPT
        ),
        assignment_id=AssignmentId(uuid.uuid4()),
        service_type="FIRE_RESCUE",
        persona_id="HEAD",
        callee_user_id=TRAINEE,
    )
    return call


async def test_a_busy_persona_ends_the_call_at_ring() -> None:
    uow: Any = _Uow()
    moved, events = await ring_now(
        uow, head_call(), now_ms=1_500, transport_ready=True, log=[], persona=persona(busy=True)
    )
    assert moved.state is DdsCallState.ENDED
    assert [event.payload["reason"] for event in events] == ["BUSY"]


def _advance(head: Persona, **kwargs: Any) -> AdvanceDdsCalls:
    return AdvanceDdsCalls(
        None,  # type: ignore[arg-type]  # `_advance` is driven directly, no transaction
        FakeClock(),
        FakeCallTransportStatus(ready=True),
        reference=_Reference(head),  # type: ignore[arg-type]
        **kwargs,
    )


async def _step(flow: AdvanceDdsCalls, call: DdsCall, now_ms: int) -> tuple[DdsCall, list[Any]]:
    return await flow._advance(_Uow(), call, now_ms, [], True)  # type: ignore[arg-type]


async def test_a_no_answer_persona_rings_out_after_the_timeout() -> None:
    flow = _advance(persona(no_answer=True), ring_timeout_ms=30_000)
    ringing = head_call().model_copy(update={"state": DdsCallState.RINGING})
    still, none = await _step(flow, ringing, 20_000)  # past answer_after_ms: it still rings
    assert still.state is DdsCallState.RINGING and none == []
    ended, events = await _step(flow, ringing, 31_000)
    assert ended.state is DdsCallState.ENDED
    assert [event.payload["reason"] for event in events] == ["NO_ANSWER"]


async def test_an_ordinary_persona_answers_after_its_own_delay() -> None:
    flow = _advance(persona().model_copy(update={"answer_after_ms": 2_000}))
    ringing = head_call().model_copy(update={"state": DdsCallState.RINGING})
    early, _ = await _step(flow, ringing, 2_500)
    assert early.state is DdsCallState.RINGING
    answered, events = await _step(flow, ringing, 3_000)
    assert answered.state is DdsCallState.CONNECTED
    assert events[0].payload["answered_by"] == "AI"


async def test_an_unanswered_inbound_call_rings_out() -> None:
    flow = _advance(persona(), ring_timeout_ms=30_000)
    ringing = head_call(DdsCallDirection.INBOUND).model_copy(update={"state": DdsCallState.RINGING})
    assert ringing.actor_user_id == TRAINEE  # the workstation it rings (callee)
    waiting, _ = await _step(
        flow, ringing, 20_000
    )  # nobody answers an INBOUND call for the trainee
    assert waiting.state is DdsCallState.RINGING
    ended, events = await _step(flow, ringing, 31_001)
    assert ended.state is DdsCallState.ENDED
    assert [event.payload["reason"] for event in events] == ["NO_ANSWER"]
