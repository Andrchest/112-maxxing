"""Who may see which section of a post-session report — one pure function, no I/O (E16 R3, D3, D11).

The report is the one read path whose viewer may be *any* of three things: an instructor, a
trainee who played the whole chain, or a trainee who played one stage of a multi-trainee session
and must not see the other stage's transcript. D3 makes visibility structural rather than
conventional, so the whole rule lives here, is pure, and is table-tested — a section is never
"hidden in the UI", it is absent from the envelope.

Three decisions, in order:

1. **May this viewer read the report at all?** `INSTRUCTOR`/`ADMIN`: always. A trainee: only a
   session they participated in — which the caller establishes with the existing
   `resolve_participant` helper — and then only if the mode's
   `SessionPolicy.report_visible_to_trainee_before_release` (D6, §10.10) is true *or* an
   instructor has released it. Otherwise `403 REPORT_NOT_RELEASED`.
2. **Which roles does this viewer speak for?** `viewer_roles` is the set of `RoleType` the
   viewer's `session_participants` rows cover *in that session*. A participant with an explicit
   `assigned_role_type` covers exactly that role; a participant with none covers every stage of
   the chain, which is §10.10's `ALL_STAGES_ONE_PARTICIPANT` (the full-cycle trainee plays both
   stages and reads their own report as the union, not as either role alone).
3. **What does each section then show?** The table below, which is the epic's ruling R3 spelled
   out. A section the viewer may not see is returned **empty or null per the openapi
   nullability** — never omitted, never a different schema. The numbers are the exception on
   purpose: `ScoreReport`'s totals are the whole session's and are never re-aggregated per
   viewer, because there is one report and one checksum (D11). Only the *per-rule* list is
   filtered, by the rule's own `applies_to_roles` (§10.14 "Applicability").

| section | shown when |
|:--|:--|
| `timeline` | per event: at least one of `viewer_roles` may receive it through `redact()` |
| `transcript`, `audio_segments`, `final_card`, `truth_vs_card_diff` | `OPERATOR_112` is a role |
| `handoff` | `OPERATOR_112 ∈ viewer_roles` or `DDS ∈ viewer_roles` |
| `dds_decisions`, `resource_timeline` | `DDS ∈ viewer_roles` |
| a `ScoreResultView` | its rule's `applies_to_roles` is empty or intersects `viewer_roles` |

`truth_vs_card_diff` is the one place `WorldTruth` reaches a human (D11). It is *not* widened
here: it rides with the operator card, because it is a statement about what the operator typed.

The timeline rule reuses `app.application.realtime.redaction.redact` per role and takes the first
non-dropped projection in **role-chain order**, exactly as §40.4 asks ("the same function serves
`GET /api/v1/sessions/{id}/events` and the report timeline, so the three read paths cannot
drift"). It invents no second whitelist. `SCORING_RULE_EVALUATED` is the one addition: it is the
report's own subject matter and is visible to every viewer who may read a report at all, which no
live `RoleModule` needs to allow because nothing is scored while a stage is running.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.realtime.effective_role import INSTRUCTOR
from app.application.realtime.redaction import RealtimeEnvelope, SourceEvent, redact
from app.domain.common.errors import DomainError
from app.domain.common.ids import SessionId
from app.domain.enums import RoleType
from app.domain.events.types import EventType
from app.domain.session.session import SimulationSession

__all__ = [
    "ReportNotReleasedError",
    "ReportVisibility",
    "report_visibility",
    "viewer_roles_of",
]

#: Visible to every report viewer regardless of role: the rule evaluations the report is *about*
#: (D11). No live `RoleModule` whitelists it because nothing is scored mid-stage.
ALWAYS_VISIBLE_EVENT_TYPES: frozenset[EventType] = frozenset({EventType.SCORING_RULE_EVALUATED})


class ReportNotReleasedError(DomainError):
    """The mode needs an instructor release and has not had one (`403 REPORT_NOT_RELEASED`)."""

    code = "REPORT_NOT_RELEASED"

    def __init__(self, session_id: SessionId) -> None:
        self.session_id = session_id
        super().__init__(
            f"the report of session {session_id} is not released to trainees yet; "
            "an instructor must release it first"
        )


def viewer_roles_of(session: SimulationSession, user: AuthenticatedUser) -> frozenset[RoleType]:
    """The `RoleType`s this viewer's participant rows cover in this session (R3, §10.10).

    An explicit `assigned_role_type` covers that role and no other. `None` is permitted only
    under `ALL_STAGES_ONE_PARTICIPANT` (§10.10), where the trainee plays every stage — so it
    covers the whole role chain. A non-participant covers nothing; the caller has already refused
    such a viewer, and an empty set here would show them an empty report rather than an error.
    """
    roles: set[RoleType] = set()
    for participant in session.participants:
        if participant.user_id != user.user_id:
            continue
        if participant.assigned_role_type is not None:
            roles.add(participant.assigned_role_type)
        else:
            roles.update(stage.role_type for stage in session.stages)
    return frozenset(roles)


@dataclass(frozen=True, slots=True)
class ReportVisibility:
    """The verdict for one viewer of one session's report. Pure data; build it with
    `report_visibility` and pass it to every projection."""

    session: SimulationSession
    is_instructor: bool
    viewer_roles: frozenset[RoleType]
    released: bool

    # -- section gates ------------------------------------------------------------------------

    @property
    def role_chain(self) -> tuple[RoleType, ...]:
        """`viewer_roles` in the session's own stage order — the order `redact` is tried in."""
        ordered: list[RoleType] = []
        for stage in self.session.stages:
            if stage.role_type in self.viewer_roles and stage.role_type not in ordered:
                ordered.append(stage.role_type)
        return tuple(ordered)

    @property
    def shows_operator_sections(self) -> bool:
        """`transcript`, `audio_segments`, `final_card`, `truth_vs_card_diff` (R3)."""
        return self.is_instructor or RoleType.OPERATOR_112 in self.viewer_roles

    @property
    def shows_handoff(self) -> bool:
        """The handoff snapshot: the hand-over is the one artefact both sides share (R3)."""
        return self.is_instructor or bool(self.viewer_roles & {RoleType.OPERATOR_112, RoleType.DDS})

    @property
    def shows_dds_sections(self) -> bool:
        """`dds_decisions` and `resource_timeline` (R3)."""
        return self.is_instructor or RoleType.DDS in self.viewer_roles

    def shows_rule(self, applies_to_roles: Sequence[RoleType]) -> bool:
        """Is this scoring rule's *result row* shown to this viewer? (R3, §10.14 "Applicability")

        An empty `applies_to_roles` means "always applies" — it is shown to everyone. The totals
        are never affected either way: they are the whole session's (D11).
        """
        if self.is_instructor or not applies_to_roles:
            return True
        return bool(self.viewer_roles & set(applies_to_roles))

    # -- the timeline -------------------------------------------------------------------------

    def timeline_entry(
        self, event: SourceEvent, *, dds_call_ids: frozenset[str] = frozenset()
    ) -> RealtimeEnvelope | None:
        """This event as this viewer may see it, or `None` when no role of theirs may (R3).

        For an instructor, `redact` is called once with `INSTRUCTOR` and returns every key. For a
        trainee it is called per role in role-chain order and the first non-dropped projection
        wins: a full-cycle trainee therefore sees their operator events through the operator's
        whitelist and their DDS events through the DDS's, which is precisely the union R3 asks
        for and precisely not a new whitelist.

        `dds_call_ids` (I3 E6c) is the session's ДДС call ids, handed to `redact` so the report
        timeline is call-scoped exactly as the sockets are (HLD 80 §80.6.2): a ДДС call's turns
        reach the ДДС viewer and never the 112 one.
        """
        if self.is_instructor:
            return redact(event, INSTRUCTOR, self.session.policy)

        if event.event_type in ALWAYS_VISIBLE_EVENT_TYPES:
            # Projected through the instructor's (unredacted) reading: a `SCORING_RULE_EVALUATED`
            # payload is the rule id, points and verdict the viewer is about to read anyway in
            # `score_report`, so redacting it here would contradict the section beside it.
            return redact(event, INSTRUCTOR, self.session.policy)

        for role in self.role_chain:
            projected = redact(event, role, self.session.policy, dds_call_ids=dds_call_ids)
            if projected is not None:
                return projected
        return None


def report_visibility(
    session: SimulationSession,
    user: AuthenticatedUser,
    *,
    released: bool,
) -> ReportVisibility:
    """The viewer's verdict, or `ReportNotReleasedError` (R3, D6).

    The caller has already established that the session exists and that a trainee viewer
    participates in it (`resolve_participant`); this function decides only what they may see.
    """
    if user.is_instructor_or_admin:
        return ReportVisibility(
            session=session,
            is_instructor=True,
            viewer_roles=frozenset(stage.role_type for stage in session.stages),
            released=released,
        )

    if not session.policy.report_visible_to_trainee_before_release and not released:
        raise ReportNotReleasedError(session.id)

    return ReportVisibility(
        session=session,
        is_instructor=False,
        viewer_roles=viewer_roles_of(session, user),
        released=released,
    )
