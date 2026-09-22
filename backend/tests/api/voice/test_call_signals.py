"""§40.6's two voice signals and its call-state cache, driven through the real call (D9).

What is asserted here is the *order of a call*, which is the thing the HLD contradicted itself
about and E11 resolved: `ring` (guarded) → `CALL_RINGING` → `voice:join` **after the commit** →
the trainee answers → the agent joins → the retry stops. Plus the two cancels: `endCall` and
`abortSession`.

The order of those middle two is the point of R2: the answer does **not** stop the retry, because
the trainee can (and a script always does) answer before the agent has arrived. Only the agent's
own first event for the call, or the call ending, stops it.

The signals are recorded rather than published (`InMemoryVoiceSignals`, see this package's
conftest) because "was it published, and was the log already committed when it was" is a question
about ordering, and a pub/sub subscriber would answer it with a race.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from app.api.container import Container
from app.application.testing.fakes import InMemoryCallStateCache, InMemoryVoiceSignals
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

from tests.api.conftest import auth
from tests.api.voice.conftest import OperatorFlow

pytestmark = pytest.mark.integration


# -- voice:join ------------------------------------------------------------------------------------


async def test_ring_publishes_voice_join_with_the_room_and_call_id_of_call_ringing(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    assert voice_signals.joins == []

    assert await flow.advance_call_flow() is True

    assert len(voice_signals.joins) == 1
    session_id, room, call_id = voice_signals.joins[0]
    assert session_id == SessionId(flow.session_id)
    assert room == f"session-{flow.session_id}"

    ringing_event = await _event_payload(flow, EventType.CALL_RINGING)
    assert room == ringing_event["room_name"]
    assert call_id == UUID(str(ringing_event["call_id"]))


async def test_voice_join_is_published_only_after_the_event_is_committed(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """A join that escaped early would send the agent into a room a rollback then erased."""
    assert await flow.advance_call_flow() is True

    # By the time the single publish is visible, `CALL_RINGING` is already readable from
    # PostgreSQL in another transaction — which is only true of a committed append.
    assert len(voice_signals.joins) == 1
    assert EventType.CALL_RINGING.value in await flow.event_types()


async def test_a_refused_ring_publishes_nothing(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """The transport is not ready, so no call starts and no agent is summoned."""
    flow.container.call_transport_status = _NeverReady()

    assert await flow.advance_call_flow() is False

    assert voice_signals.joins == []
    assert EventType.CALL_RINGING.value not in await flow.event_types()


async def test_voice_join_is_republished_while_the_stage_is_still_ringing(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """§40.6: "the backend re-publishes every `VOICE_JOIN_RETRY_MS` while the stage is RINGING"."""
    flow.container.settings = flow.container.settings.model_copy(
        update={"voice_join_retry_ms": 0}  # every tick is due, so the test needs no sleep
    )
    assert await flow.advance_call_flow() is True
    assert len(voice_signals.joins) == 1

    # Two more ticks: nothing fires, but the self-healing signal is re-sent.
    assert await flow.advance_call_flow() is False
    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == 3
    rooms = {room for _session, room, _call in voice_signals.joins}
    assert rooms == {f"session-{flow.session_id}"}
    # Still one call: the retry re-publishes, it does not re-ring.
    assert (await flow.event_types()).count(EventType.CALL_RINGING.value) == 1


async def test_the_retry_respects_voice_join_retry_ms(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """A long interval means the very next tick must not re-publish."""
    flow.container.settings = flow.container.settings.model_copy(
        update={"voice_join_retry_ms": 600_000}
    )
    assert await flow.advance_call_flow() is True

    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == 1


async def test_the_retry_survives_an_answer_the_agent_was_too_slow_for(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """R2: answering must not silence `voice:join` — only the agent's own arrival may (E19-E3).

    Until E20 the retry was gated on the *stage* being `RINGING`, so a trainee (or a script) who
    answered within a tick left the call `CONNECTED` with no agent in the room, no further join
    signal and no error anywhere. This is that exact sequence: ring, answer immediately, tick.
    """
    flow.container.settings = flow.container.settings.model_copy(update={"voice_join_retry_ms": 0})
    assert await flow.advance_call_flow() is True
    answered = await flow.post("/operator/call/answer")
    assert answered.status_code == 200, answered.text
    published_before = len(voice_signals.joins)

    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == published_before + 1
    # The same call, re-advertised — not a second one.
    ringing_event = await _event_payload(flow, EventType.CALL_RINGING)
    assert voice_signals.joins[-1][2] == UUID(str(ringing_event["call_id"]))
    assert (await flow.event_types()).count(EventType.CALL_RINGING.value) == 1


async def test_the_retry_stops_once_the_agent_has_appended_an_event_for_the_call(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """The ack is the agent's own first event for that `call_id` (R2) — the only one available."""
    flow.container.settings = flow.container.settings.model_copy(update={"voice_join_retry_ms": 0})
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    ringing_event = await _event_payload(flow, EventType.CALL_RINGING)
    call_id = UUID(str(ringing_event["call_id"]))

    await _append_agent_event(flow, call_id)
    published_before = len(voice_signals.joins)

    assert await flow.advance_call_flow() is False
    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == published_before


async def test_an_agent_event_of_a_previous_call_does_not_ack_the_current_one(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """The ack is per `call_id`, so a re-dial is advertised again from scratch."""
    flow.container.settings = flow.container.settings.model_copy(update={"voice_join_retry_ms": 0})
    assert await flow.advance_call_flow() is True
    await _append_agent_event(flow, uuid4())
    published_before = len(voice_signals.joins)

    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == published_before + 1


async def test_the_retry_stops_once_the_call_has_ended(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """An `ENDED` call needs nobody in its room, agent or not."""
    flow.container.settings = flow.container.settings.model_copy(update={"voice_join_retry_ms": 0})
    assert await flow.advance_call_flow() is True
    assert (await flow.post("/operator/call/answer")).status_code == 200
    ended = await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text
    published_before = len(voice_signals.joins)

    assert await flow.advance_call_flow() is False

    assert len(voice_signals.joins) == published_before


async def _append_agent_event(flow: OperatorFlow, call_id: UUID) -> None:
    """One `USER_SPEECH_STARTED` for `call_id`, as the voice agent appends it (D9, §20.8)."""
    async with flow.container.unit_of_work() as uow:
        await uow.events.append(
            SessionId(flow.session_id),
            [
                DomainEvent(
                    event_type=EventType.USER_SPEECH_STARTED,
                    actor=ActorRef(actor_type=ActorType.MODEL),
                    monotonic_offset_ms=1000,
                    payload={
                        "call_id": str(call_id),
                        "turn_index": 0,
                        "turn_id": str(uuid4()),
                        "at_offset_ms": 1000,
                        "vad_provider": "test",
                    },
                )
            ],
        )
        await uow.commit()


# -- voice:cancel ----------------------------------------------------------------------------------


async def test_end_call_publishes_voice_cancel_with_reason_hangup(
    connected: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    response = await connected.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert response.status_code == 200, response.text

    assert len(voice_signals.cancels) == 1
    session_id, call_id, reason, at_offset_ms = voice_signals.cancels[0]
    assert session_id == SessionId(connected.session_id)
    assert reason == "HANGUP"
    assert at_offset_ms >= 0
    ringing_event = await _event_payload(connected, EventType.CALL_RINGING)
    assert call_id == UUID(str(ringing_event["call_id"]))


async def test_a_transport_lost_hang_up_keeps_its_own_reason(
    connected: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """§40.6's enum has `TRANSPORT_LOST` too, and it is not the same thing as a hang-up."""
    response = await connected.post("/operator/call/end", json={"reason": "TRANSPORT_LOST"})
    assert response.status_code == 200, response.text

    assert voice_signals.cancels[0][2] == "TRANSPORT_LOST"


async def test_a_refused_end_call_publishes_nothing(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    """No call to end: the command is refused and the agent is told nothing."""
    response = await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})

    assert response.status_code == 409
    assert voice_signals.cancels == []


async def test_abort_session_publishes_voice_cancel_with_reason_abort(
    connected: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    response = await connected.client.post(
        connected.url("/abort"),
        headers=auth(connected.instructor_token),
        json={"reason": "instructor stopped the exercise"},
    )
    assert response.status_code == 200, response.text

    assert len(voice_signals.cancels) == 1
    _session, _call_id, reason, _at = voice_signals.cancels[0]
    assert reason == "ABORT"


async def test_aborting_a_session_with_no_call_cancels_nothing(
    flow: OperatorFlow, voice_signals: InMemoryVoiceSignals
) -> None:
    response = await flow.client.post(
        flow.url("/abort"),
        headers=auth(flow.instructor_token),
        json={"reason": "never started"},
    )
    assert response.status_code == 200, response.text

    assert voice_signals.cancels == []


# -- session:{id}:call_state -----------------------------------------------------------------------


async def test_ring_and_answer_and_hang_up_each_refresh_the_call_state_cache(
    flow: OperatorFlow, call_state_cache: InMemoryCallStateCache
) -> None:
    session_id = SessionId(flow.session_id)

    assert await flow.advance_call_flow() is True
    assert json.loads(call_state_cache.values[session_id])["phase"] == "RINGING"

    assert (await flow.post("/operator/call/answer")).status_code == 200
    assert json.loads(call_state_cache.values[session_id])["phase"] == "CONNECTED"

    ended = await flow.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text
    assert json.loads(call_state_cache.values[session_id])["phase"] == "ENDED"


async def test_losing_the_call_state_cache_changes_no_answer(
    connected: OperatorFlow, call_state_cache: InMemoryCallStateCache
) -> None:
    """§40.6: a FLUSHALL costs "two read caches", never a trainee-visible fact (SPEC §31)."""
    before = (await connected.snapshot()).json()["call_state"]

    call_state_cache.values.clear()  # FLUSHALL against a running simulation
    after = (await connected.snapshot()).json()["call_state"]

    assert after == before
    assert after["phase"] == "CONNECTED"
    assert after["room_name"] == f"session-{connected.session_id}"


# -- helpers ---------------------------------------------------------------------------------------


class _NeverReady:
    """A `CallTransportStatus` whose media plane is down."""

    async def transport_ready(self, session_id: SessionId) -> bool:
        return False


async def _event_payload(flow: OperatorFlow, event_type: EventType) -> dict[str, object]:
    """The payload of the first event of this type in the session's log."""
    container: Container = flow.container
    async with container.unit_of_work() as uow:
        events = await uow.events.read(SessionId(flow.session_id))
        await uow.commit()
    for event in events:
        if event.event_type is event_type:
            return dict(event.payload)
    raise AssertionError(f"no {event_type.value} in the log")
