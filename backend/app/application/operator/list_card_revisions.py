"""`listCardRevisions` — the card's revision history (`openapi.yaml`, SPEC §9, §10.9).

Source `CARD_REVISIONS` of the operator's `DataVisibilityPolicy`. `openapi.yaml`: *"This is what
makes 'the final card is NOT enough' (SPEC §9) visible in the UI and the report."*

Ordering and paging are the repository's (`ORDER BY revision_no ASC`, `LIMIT`/`OFFSET`), and the
`total` is the count *after* the optional `field_path` filter, so a client paging one field is
not told how many revisions the whole card has.

The visibility check is `get_card`'s, reused rather than restated: a caller who may not read the
card may not read its history either, and `CARD_REVISIONS` and `OPERATOR_CARD` are in the same
`DataVisibilityPolicy.sources` set for every role that has either.
"""

from __future__ import annotations

from app.application.auth.get_current_user import AuthenticatedUser
from app.application.operator.get_card import load_card_for_reader
from app.application.operator.views import CardRevisionView, revision_view
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.domain.common.ids import SessionId

__all__ = ["ListCardRevisions"]


class ListCardRevisions:
    """`listCardRevisions` (`openapi.yaml`): one page of the card's history."""

    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def __call__(
        self,
        session_id: SessionId,
        user: AuthenticatedUser,
        *,
        field_path: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[tuple[CardRevisionView, ...], int]:
        """The page, ascending by `revision_no`, and the unpaged total after the filter."""
        async with self._unit_of_work() as uow:
            _session, card = await load_card_for_reader(uow, session_id, user)
            revisions, total = await uow.operator_cards.list_revisions(
                card.card_id, field_path=field_path, limit=limit, offset=offset
            )
            await uow.commit()
        return tuple(revision_view(revision) for revision in revisions), total
