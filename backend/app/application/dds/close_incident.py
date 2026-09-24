"""`closeDdsIncident` — close the incident and end the session (`openapi.yaml`, §10.8).

One command, two machines, one transaction — the DDS mirror image of `completeOperatorStage`:

1. the **stage** machine fires `close` (`RESOLVED -> CLOSED`, unguarded). `CLOSED` is the DDS
   stage's terminal state, so `fire_stage_trigger` also produces `ROLE_STAGE_COMPLETED`;
2. the **session** machine then fires `complete` when the DDS stage is the last `role_chain`
   entry — through `app.application.handoff.complete_session`, the one place that knows the real
   `SESSION_COMPLETED.total_events` — or `begin_role_transition` when a further stage follows.

`x-emits` is `[DDS_INCIDENT_CLOSED, ROLE_STAGE_COMPLETED, STAGE_STATE_CHANGED,
SCORING_RULE_EVALUATED, SESSION_COMPLETED]`. This command still appends only the first four, in
that order (the two stage events are re-ordered out of the aggregate's own order here: the
contract lists the completion before the state change, and a consumer reading `x-emits` as the
promise should get exactly that) — `SESSION_COMPLETED` is `complete_session`'s own append, inside
this same call when this is the last stage, and `SCORING_RULE_EVALUATED` is appended **after**
this whole command's transaction has committed, by `score_completed_session`
(`app.application.handoff.complete_session`), which `app.api.routers.dds.close_dds_incident` calls
once its commit is already durable (epic E15-B; see that module's docstring for why scoring cannot
share this command's own transaction). `backend/tests/api/dds/test_full_cycle.py` now asserts the
emitted list **plus** the router-appended `SCORING_RULE_EVALUATED` rows equals `x-emits` in full.

**Memo mode (I3 E5a, HLD 70 §70.4.4, D16).** Under `dds_mode: MEMO_STATUSES` the stage rests in
`ACKNOWLEDGED` and this command fires `close` **twice** in its one Unit of Work: first the
additive row `ACKNOWLEDGED --close--> RESOLVED`, guarded by `memo_all_legs_terminal` (every leg
Работы завершены, Не принята or Отказ от выполнения работ — a leg still open is the ordinary
`409 INVALID_TRANSITION`), then `RESOLVED --close--> CLOSED`. `RESOLVED` is therefore never
observed at rest in memo mode, and the events are that operation's memo `x-emits`:
`STAGE_STATE_CHANGED`, `DDS_INCIDENT_CLOSED`, `ROLE_STAGE_COMPLETED`, `STAGE_STATE_CHANGED`. The
legs' response statuses are theirs and are left as they are.

**The ДДС phone (I3 E6c, HLD 80 §80.3.2).** Closing the incident is the DDS stage's completion,
so every ДДС call still live in the session is ended by SYSTEM (`DDS_CALL_ENDED {reason: ABORT}`)
in this same Unit of Work, before the closure's own events, and `voice:cancel:{session_id}
{call_id, reason: ABORT}` is published for each after the commit — the voice agent drops the call.

**Release (HLD gap, analyst §7 #13).** §10.13 gives `DDS_INCIDENT_CLOSED` a
`released_resource_ids` key without saying what "released" does. The reading closest to SPEC §11
is taken: the units still attached to any leg are named in the payload and **detached**
(`emergency_resources.assignment_id = NULL`) — the work item is over, so nothing hangs on it any
more — while their statuses are left to the engine, which walks them home through `finish_work`
and `return_to_base`. The history survives regardless: a leg's `dispatched_resource_ids` is
projected from the append-only `resource_state_changes`, never from the live attachment.
"""

from __future__ import annotations

from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import DdsCommandContext, DdsCommandGate
from app.application.dds.dds_call_flow import CallSignal, end_live_calls, publish_signals
from app.application.handoff.complete_session import SYSTEM_ACTOR, complete_session
from app.application.ports.clock import Clock
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.sessions.queries import SessionDetailView, assemble_session_detail
from app.domain.common.ids import ResourceId, SessionId
from app.domain.enums import ClosureReason, DDSStageState
from app.domain.events.session_event import DomainEvent
from app.domain.events.types import EventType

__all__ = ["ACTION_ID", "CloseDdsIncident"]

ACTION_ID = "close"
"""`openapi.yaml`'s `x-action` for `closeDdsIncident`."""


class CloseDdsIncident:
    """`closeDdsIncident` (`openapi.yaml`): `RESOLVED -> CLOSED` (memo: from `ACKNOWLEDGED`
    through `RESOLVED`), then the session machine."""

    def __init__(
        self,
        gate: DdsCommandGate,
        clock: Clock,
        voice_signals: VoiceSignalPublisher | None = None,
    ) -> None:
        self._gate = gate
        self._clock = clock
        self._voice_signals = voice_signals

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        closure_reason: ClosureReason,
        comment_ru: str | None = None,
    ) -> SessionDetailView:
        """Close the incident, release the units, complete the session if this was the last stage.

        `comment_ru` is `CloseIncidentRequest`'s optional free-text closure comment (E17 R2). It
        rides in `DDS_INCIDENT_CLOSED.comment_ru`, additive and nullable in the §10.13 catalog —
        DDS/INSTRUCTOR only, since `OPERATOR_112` never receives this event type at all (D3).
        `score()` never reads it: no evaluator's evidence path touches `comment_ru`.
        """
        signals: list[CallSignal] = []
        async with self._gate.open(session_id, user, ACTION_ID) as ctx:
            released = _attached_units(ctx)
            call_events, signals = await end_live_calls(ctx.uow, session_id, ctx.now_ms)
            if call_events:
                await ctx.append(call_events)

            resolved_events: list[DomainEvent] = []
            if ctx.memo and ctx.stage_state is DDSStageState.ACKNOWLEDGED:
                session, resolved_events = ctx.session.fire_stage_trigger(
                    ctx.stage.role_stage_id,
                    ACTION_ID,
                    actor=ctx.actor,
                    now_ms=ctx.now_ms,
                    runtime=ctx.guard_runtime(),
                    assignment=ctx.primary,
                )
                await ctx.save_session(session)

            session, stage_events = ctx.session.fire_stage_trigger(
                ctx.stage.role_stage_id,
                ACTION_ID,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                runtime=ctx.guard_runtime(),
                assignment=ctx.primary,
                resources=ctx.attached_units(),
            )
            await ctx.save_session(session)
            await ctx.mirror_legs(closed_at_offset_ms=ctx.now_ms, closure_reason=closure_reason)
            for resource_id in released:
                await ctx.uow.resources.attach(ctx.session_id, resource_id, None)

            await ctx.append(
                [
                    *resolved_events,
                    _closed(ctx, closure_reason, released, comment_ru),
                    *_in_contract_order(stage_events),
                ]
            )

            if ctx.session.next_stage_after(ctx.stage) is not None:
                moved, transition_events = ctx.session.begin_role_transition(
                    actor=SYSTEM_ACTOR, now_ms=ctx.now_ms, runtime=ctx.guard_runtime()
                )
                await ctx.save_session(moved)
                await ctx.append(transition_events)
            else:
                ctx.session, _events = await complete_session(
                    ctx.uow,
                    ctx.session,
                    clock=self._clock,
                    now_ms=ctx.now_ms,
                    last_seq_no=ctx.last_seq_no,
                    runtime=ctx.guard_runtime(),
                )

            detail = await assemble_session_detail(
                ctx.uow, ctx.session, viewer=user, clock=self._clock
            )
        # The gate committed when the block closed; the cancels follow the commit (§40.6).
        await publish_signals(self._voice_signals, session_id, signals)
        return detail


def _attached_units(ctx: DdsCommandContext) -> tuple[ResourceId, ...]:
    """Every unit still hanging on any leg of this work item, in `callsign` order."""
    ids = {leg.assignment_id for leg in ctx.legs}
    return tuple(
        stored.resource.resource_id
        for stored in sorted(ctx.board, key=lambda item: item.resource.callsign)
        if stored.assignment_id in ids
    )


def _in_contract_order(stage_events: list[DomainEvent]) -> list[DomainEvent]:
    """`fire_stage_trigger`'s two events in `x-emits` order: completion, then state change.

    The aggregate returns `STAGE_STATE_CHANGED` first and `ROLE_STAGE_COMPLETED` second, which is
    the order every other stage command appends them in. `closeDdsIncident` is the one operation
    whose `x-emits` states the opposite order, and the contract is the promise a consumer reads.
    """
    completed = [
        event for event in stage_events if event.event_type is EventType.ROLE_STAGE_COMPLETED
    ]
    others = [
        event for event in stage_events if event.event_type is not EventType.ROLE_STAGE_COMPLETED
    ]
    return [*completed, *others]


def _closed(
    ctx: DdsCommandContext,
    closure_reason: ClosureReason,
    released: tuple[ResourceId, ...],
    comment_ru: str | None,
) -> DomainEvent:
    """`DDS_INCIDENT_CLOSED` (TRAINEE) — one per trainee action, carrying the primary leg (R5)."""
    return DomainEvent(
        event_type=EventType.DDS_INCIDENT_CLOSED,
        actor=ctx.actor,
        monotonic_offset_ms=ctx.now_ms,
        payload={
            "assignment_id": UUID(str(ctx.primary.assignment_id)),
            "closure_reason": closure_reason.value,
            "released_resource_ids": [str(resource_id) for resource_id in released],
            "at_offset_ms": ctx.now_ms,
            "actor_user_id": UUID(str(ctx.actor.actor_id)),
            "comment_ru": comment_ru,
        },
    )
