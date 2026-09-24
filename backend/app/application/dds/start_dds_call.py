"""`startDdsCall` — the ДДС trainee places a call (I3 E6b, HLD `80-telephony.md` §80.3.2, §80.3.4,
`openapi.yaml`).

Fires `[*] --start--> DIALING` (`DDS_CALL_STARTED`) and, when the transport is already up, `ring`
in the same transaction — and, for a claimant whose 112 call is live, `busy` right after it
(`DDS_CALL_ENDED {reason: BUSY}`), which is why the `201` can carry an `ENDED` call. A call left
`DIALING` is rung by `AdvanceDdsCalls` on a later tick.

`guard_dds_call_allowed` (§80.3.2) is this command's gate, in the DDS pipeline's fixed order
(`DdsCommandGate.open`): session `ACTIVE` (`409 SESSION_NOT_ACTIVE`), a ДДС participant trainee of
the active DDS stage (`403`), and the kind's action id in `available_actions` — which holds only
under `dds_brigade_call: ON`, in memo mode, in `RECEIVED` / `ACKNOWLEDGED` (`call_claimant` E6b,
`call_service_head` E6c, `call_112` E6d), else `409 ACTION_NOT_AVAILABLE`. Then one line per
workstation: a live call of the same user ⇒ `409 DDS_LINE_BUSY`.

**The service head (§80.3.3, §80.4.1; I3 E6c).** `assignment_id` names the leg (`422` without
one; `404` for a leg not on this card) and the caller must play it (`plays_leg`, else `403
FORBIDDEN_FOR_SERVICE`). `dialed` is the service's number (`phone_extension`: its catalog `code`,
else `7` + its position), and the persona is resolved from the session's reference pack by the
service's catalog category (`code` over `kind`) unless the scenario names one for the service
(R42) — that override arrives through a narrow probe the composition root binds runner-side
(`persona_override`), because the script itself is never handed to a DDS command (INV 3). The
resolved `persona_id` rides on `DDS_CALL_STARTED` (P4).

**The claimant (§80.3.4).** `dialed` is the frozen snapshot's `caller.phone` (digits), falling back
to `caller.phone_aon`; a card with neither number has nobody to call back (`409
ACTION_NOT_AVAILABLE`). No persona is resolved: the scenario's `CallerProfile` is the claimant, and
the voice agent runs the frozen caller chain for this `call_id` (`voice:join {call_kind:
CLAIMANT}`).

**112 (§80.3.4; I3 E6d).** `dialed` is `"112"` (the dial plan's first row, §80.3.5) and the persona
is the pack's `applies: {kind: OPERATOR_112}` one — the AI 112 operator, who knows the frozen
snapshot and nothing else and asks for REQ-5332's checklist (`responder_templates.py`). The human
112 trainee on a second line is owner question Q1 — the reserved hook (`answered_by: TRAINEE`,
E6g) has no behaviour here: the AI always answers.

**The endpoint** is `BROWSER` in E6b; the softphone endpoint (`SIP`, a live `sip:binding:{user}`)
is E6e's (§80.3.7). The answer carries the room-scoped token for the browser endpoint.

After the commit, and only then: `voice:join` for a call that is now `RINGING` (§40.6's rule, per
call). The command never touches the 112 call or its `session:{id}:call_state` (§80.3.6).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.dds.command_context import (
    ActionNotAvailableError,
    DdsCommandContext,
    DdsCommandGate,
)
from app.application.dds.dds_call_flow import CallSignal, publish_signals, ring_now
from app.application.dds.dds_call_views import DdsCallView, dds_call_view
from app.application.dds.set_service_status import check_leg_bound
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
from app.domain.dds.personas import OPERATOR_112_KIND, Persona, resolve_persona
from app.domain.enums import ServiceId
from app.domain.events.types import EventType
from app.domain.layers.handoff import HandoffSnapshot
from app.domain.routing.dial_plan import phone_extension

__all__ = [
    "ACTION_ID_BY_KIND",
    "DIALED_112",
    "PersonaOverrideProbe",
    "StartDdsCall",
    "StartedDdsCall",
    "claimant_number",
    "service_head_target",
]

type PersonaOverrideProbe = Callable[[SessionId, str], Awaitable[str | None]]
"""`(session_id, service_id) → persona id` a scenario names for that service (R42), bound
runner-side by the composition root (INV 3: no DDS command is handed the script)."""


async def _no_override(_session_id: SessionId, _service_id: str) -> str | None:
    return None


ACTION_ID_BY_KIND: dict[DdsCallKind, str] = {
    DdsCallKind.SERVICE_HEAD: "call_service_head",
    DdsCallKind.CLAIMANT: "call_claimant",
    DdsCallKind.OPERATOR_112: "call_112",
}
"""`openapi.yaml`'s `x-action` of `startDdsCall`, per kind (HLD 80 §80.5)."""

_PHONE_FIELDS = ("caller.phone", "caller.phone_aon")
DIALED_112 = "112"
"""What a call to 112 dials (HLD 80 §80.3.5's first row)."""
_NON_DIGIT = re.compile(r"\D")


class DdsCallRequestError(DomainError):
    """`assignment_id` given for a kind that takes none, or missing for `SERVICE_HEAD`
    (`422 VALIDATION_ERROR`)."""

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


async def service_head_target(
    ctx: DdsCommandContext,
    assignment_id: AssignmentId,
    override: str | None,
) -> tuple[ServiceId, str, Persona | None]:
    """The leg's service, the number dialled and the persona that answers (§80.3.5, §80.4.1)."""
    leg = ctx.leg(assignment_id)
    entry = None if ctx.service_catalog is None else ctx.service_catalog.get(leg.service_type)
    dialed = (
        None
        if ctx.service_catalog is None
        else phone_extension(ctx.service_catalog, leg.service_type)
    )
    persona = resolve_persona(
        ctx.personas,
        code=None if entry is None else entry.code,
        kind=None if entry is None else entry.kind.value,
        override=override,
    )
    return leg.service_type, dialed or str(leg.service_type), persona


class StartDdsCall:
    """`startDdsCall` (`openapi.yaml`)."""

    def __init__(
        self,
        gate: DdsCommandGate,
        ids: IdGenerator,
        call_transport: CallTransportStatus,
        tokens: VoiceTokenService,
        voice_signals: VoiceSignalPublisher | None = None,
        persona_override: PersonaOverrideProbe = _no_override,
    ) -> None:
        self._gate = gate
        self._ids = ids
        self._call_transport = call_transport
        self._tokens = tokens
        self._voice_signals = voice_signals
        self._persona_override = persona_override

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
            if kind is DdsCallKind.SERVICE_HEAD and assignment_id is None:
                raise DdsCallRequestError("a SERVICE_HEAD call needs the leg's assignment_id")
            service_type: ServiceId | None = None
            persona: Persona | None = None
            dialed: str | None
            if assignment_id is not None:
                check_leg_bound(ctx.leg(assignment_id), user.user_id)
            live = await ctx.uow.dds_calls.live_for_user(session_id, user.user_id)
            if live is not None:
                raise DdsLineBusyError(live.call_id)
            if kind is DdsCallKind.SERVICE_HEAD:
                assert assignment_id is not None
                override = await self._persona_override(
                    session_id, str(ctx.leg(assignment_id).service_type)
                )
                service_type, dialed, persona = await service_head_target(
                    ctx, assignment_id, override
                )
            elif kind is DdsCallKind.OPERATOR_112:
                # I3 E6d (§80.3.4): the AI 112 operator answers (owner Q1's default).
                dialed = DIALED_112
                persona = resolve_persona(ctx.personas, code=None, kind=OPERATOR_112_KIND)
            else:
                dialed = claimant_number(ctx.snapshot)
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
                assignment_id=assignment_id,
                service_type=service_type,
                persona_id=None if persona is None else persona.id,
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
                persona=persona,
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
        return StartedDdsCall(
            call=dds_call_view(
                call, user, persona_title_ru=None if persona is None else persona.title_ru
            ),
            voice=voice,
        )
