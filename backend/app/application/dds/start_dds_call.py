"""`startDdsCall` — the ДДС trainee places a call (I3 E6b, HLD `80-telephony.md` §80.3.2, §80.3.4,
`openapi.yaml`).

Fires `[*] --start--> DIALING` (`DDS_CALL_STARTED`) and, when the transport is already up, `ring`
in the same transaction — and, for a claimant whose 112 call is live, `busy` right after it
(`DDS_CALL_ENDED {reason: BUSY}`), which is why the `201` can carry an `ENDED` call. A call left
`DIALING` is rung by `AdvanceDdsCalls` on a later tick.

`guard_dds_call_allowed` (§80.3.2) is this command's gate, in the DDS pipeline's fixed order
(`DdsCommandGate.open`): session `ACTIVE` (`409 SESSION_NOT_ACTIVE`), a ДДС participant trainee of
the active DDS stage (`403`), and the kind's action id in `available_actions` — which holds only
under `dds_brigade_call: ON`, in memo mode, in `RECEIVED` / `ACKNOWLEDGED`, and only for a kind an
epic has landed (`call_claimant` in E6b; `call_service_head` E6c, `call_112` E6d), else `409
ACTION_NOT_AVAILABLE`. Then one line per workstation: a live call of the same user ⇒ `409
DDS_LINE_BUSY`.

**The claimant (§80.3.4).** `dialed` is the frozen snapshot's `caller.phone` (digits), falling back
to `caller.phone_aon`; a card with neither number has nobody to call back (`409
ACTION_NOT_AVAILABLE`). No persona is resolved: the scenario's `CallerProfile` is the claimant, and
the voice agent runs the frozen caller chain for this `call_id` (`voice:join {call_kind:
CLAIMANT}`).

**The endpoint** is `BROWSER` in E6b; the softphone endpoint (`SIP`, a live `sip:binding:{user}`)
is E6e's (§80.3.7). The answer carries the room-scoped token for the browser endpoint.

After the commit, and only then: `voice:join` for a call that is now `RINGING` (§40.6's rule, per
call). The command never touches the 112 call or its `session:{id}:call_state` (§80.3.6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import ActionNotAvailableError, DdsCommandGate
from app.application.dds.dds_call_flow import CallSignal, publish_signals, ring_now
from app.application.dds.dds_call_views import DdsCallView, dds_call_view
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.id_generator import IdGenerator
from app.application.ports.voice_signal_publisher import VoiceSignalPublisher
from app.application.ports.voice_token_service import MintedVoiceToken, VoiceTokenService
from app.domain.common.errors import DomainError
from app.domain.common.ids import AssignmentId, SessionId
from app.domain.dds.call import (
    CallEndpoint,
    CallSelectionReason,
    DdsCallDirection,
    DdsCallKind,
    DdsCallState,
    DdsLineBusyError,
    start_call,
)
from app.domain.events.types import EventType
from app.domain.layers.handoff import HandoffSnapshot

__all__ = ["ACTION_ID_BY_KIND", "StartDdsCall", "StartedDdsCall", "claimant_number"]

ACTION_ID_BY_KIND: dict[DdsCallKind, str] = {
    DdsCallKind.SERVICE_HEAD: "call_service_head",
    DdsCallKind.CLAIMANT: "call_claimant",
    DdsCallKind.OPERATOR_112: "call_112",
}
"""`openapi.yaml`'s `x-action` of `startDdsCall`, per kind (HLD 80 §80.5)."""

_PHONE_FIELDS = ("caller.phone", "caller.phone_aon")
_NON_DIGIT = re.compile(r"\D")


class DdsCallRequestError(DomainError):
    """`assignment_id` given for a kind that takes none (`422 VALIDATION_ERROR`)."""

    code = "VALIDATION_ERROR"


@dataclass(frozen=True)
class StartedDdsCall:
    """`openapi.yaml`'s `StartDdsCallResponse`: the call, and its token for the browser endpoint."""

    call: DdsCallView
    voice: MintedVoiceToken | None


def claimant_number(snapshot: HandoffSnapshot) -> str | None:
    """The claimant's digits from the frozen card (REQ-5917: the number on the card), or `None`."""
    for field in _PHONE_FIELDS:
        value = snapshot.card_values.get(field)
        if isinstance(value, str):
            digits = _NON_DIGIT.sub("", value)
            if digits:
                return digits
    return None


class StartDdsCall:
    """`startDdsCall` (`openapi.yaml`)."""

    def __init__(
        self,
        gate: DdsCommandGate,
        ids: IdGenerator,
        call_transport: CallTransportStatus,
        tokens: VoiceTokenService,
        voice_signals: VoiceSignalPublisher | None = None,
    ) -> None:
        self._gate = gate
        self._ids = ids
        self._call_transport = call_transport
        self._tokens = tokens
        self._voice_signals = voice_signals

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        kind: DdsCallKind,
        assignment_id: AssignmentId | None = None,
    ) -> StartedDdsCall:
        """Start the call; ring it when the transport is up; answer with the view and the token."""
        signals: list[CallSignal] = []
        async with self._gate.open(session_id, user, ACTION_ID_BY_KIND[kind]) as ctx:
            if kind is not DdsCallKind.SERVICE_HEAD and assignment_id is not None:
                raise DdsCallRequestError(f"a {kind.value} call takes no assignment_id")
            live = await ctx.uow.dds_calls.live_for_user(session_id, user.user_id)
            if live is not None:
                raise DdsLineBusyError(live.call_id)
            dialed = claimant_number(ctx.snapshot) if kind is DdsCallKind.CLAIMANT else None
            if dialed is None:
                raise ActionNotAvailableError(ACTION_ID_BY_KIND[kind], ctx.stage_state)
            call, started = start_call(
                call_id=UUID(str(self._ids.new())),
                session_id=session_id,
                kind=kind,
                direction=DdsCallDirection.OUTBOUND,
                dialed=dialed,
                endpoint=CallEndpoint.BROWSER,
                actor=ctx.actor,
                now_ms=ctx.now_ms,
                selection_reason=CallSelectionReason.BROWSER_BUTTON,
            )
            stored = await ctx.append([started])
            # `append` may put card-status deadline events around ours (flush-before-append).
            started_id = next(
                event.id for event in stored if event.event_type is EventType.DDS_CALL_STARTED
            )
            await ctx.uow.dds_calls.add(call, started_event_id=UUID(str(started_id)))
            call, events = await ring_now(
                ctx.uow,
                call,
                now_ms=ctx.now_ms,
                transport_ready=await self._call_transport.transport_ready(session_id),
                log=ctx.full_log,
            )
            if events:
                await ctx.append(events)
            if call.state is DdsCallState.RINGING:
                signals.append(CallSignal(call))
        # The gate committed when the block above closed; the signal follows the commit (§40.6).
        await publish_signals(self._voice_signals, session_id, signals)
        voice = (
            self._tokens.mint(room_name=call.room, participant_identity=str(user.user_id))
            if call.live and call.endpoint is CallEndpoint.BROWSER
            else None
        )
        return StartedDdsCall(call=dds_call_view(call, user), voice=voice)
