"""`getOperatorCard` — the current incident card (`openapi.yaml`, §10.9, D3).

A *read*, so it does not go through `OperatorCommandGate`: there is no action to check, no
transition to fire and nothing to append. What it does share with the commands is D8's first gate
and D3's visibility rule, and both live here so that `getOperatorCard`, `listCardRevisions` and
the snapshot cannot disagree about who may see the card:

* the `OPERATOR_112` participant of the session sees it — `VisibilitySource.OPERATOR_CARD` is in
  `Operator112Module`'s `DataVisibilityPolicy.sources`;
* an `INSTRUCTOR` or `ADMIN` sees it — the instructor console shows the trainee's card live, and
  SPEC §7 gives the instructor observation without participation;
* **a `DDS` participant never sees it** (D3, SPEC §10, §42 test 3). `DDSModule`'s policy does not
  list `OPERATOR_CARD`, and that is the check made here — not a hard-coded role comparison — so
  adding a role module with a different policy needs no change in this file.

Everything else is `403 FORBIDDEN_FOR_ROLE`, and a session the caller may not observe at all is
the same `403`: a trainee who guesses a session id learns only that they may not see it.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.views import OperatorCardView, card_view
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.sessions.authorisation import can_observe
from app.application.sessions.queries import ForbiddenForRoleError
from app.application.sessions.start_session import SessionNotFoundError
from app.domain.common.ids import SessionId
from app.domain.layers.operator_card import OperatorCard
from app.domain.roles.registry import ROLE_MODULES
from app.domain.roles.visibility import VisibilitySource
from app.domain.session.session import SimulationSession

__all__ = ["CardNotFoundError", "GetOperatorCard", "load_card_for_reader", "may_read_card"]


class CardNotFoundError(SessionNotFoundError):
    """The incident has no card row (`404`). Session creation always makes one."""


def may_read_card(session: SimulationSession, user: AuthenticatedUser) -> bool:
    """May this caller read the live `OperatorCard` of this session (D3, §10.9)?

    Decided by the acting role's `DataVisibilityPolicy`, never by a role name written here.
    """
    if user.is_instructor_or_admin:
        return True
    for stage in session.stages:
        if stage.participant_user_id != user.user_id:
            continue
        module = ROLE_MODULES.get(stage.role_type)
        if module is not None and module.visibility_policy.may_read(VisibilitySource.OPERATOR_CARD):
            return True
    return False


async def load_card_for_reader(
    uow: UnitOfWork, session_id: SessionId, user: AuthenticatedUser
) -> tuple[SimulationSession, OperatorCard]:
    """The session and its card, after the observation and visibility checks (shared read path)."""
    session = await uow.sessions.get(session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    if not can_observe(session, user) or not may_read_card(session, user):
        raise ForbiddenForRoleError(f"the caller may not read the card of session {session_id}")
    card = await uow.operator_cards.get(session.incident.incident_id)
    if card is None:
        raise CardNotFoundError(session_id)
    return session, card


class GetOperatorCard:
    """`getOperatorCard` (`openapi.yaml`): the current incident card."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(self, session_id: SessionId, user: AuthenticatedUser) -> OperatorCardView:
        """The card, if this caller may read it."""
        async with self._unit_of_work() as uow:
            _session, card = await load_card_for_reader(uow, session_id, user)
            await uow.commit()
        return card_view(card)
