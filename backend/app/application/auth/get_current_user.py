"""`authenticate_token` — bearer token → `AuthenticatedUser` (D8).

One pure application function over the `TokenService` and `UserRepository` ports, deliberately not
a FastAPI dependency: E7-C's WebSocket handler authenticates from the `?token=…` query parameter
of `/api/v1/ws/sessions/{id}` (D8) and cannot use an HTTP `Depends` chain to do it. The REST
`get_current_user` dependency in `app.api.security` is a thin wrapper around this same function,
so the two entry points can never drift apart.

Everything that makes a token unusable — missing, malformed, expired, signed with another secret,
naming a user that no longer exists, or naming one that has been deactivated since the token was
minted — raises `InvalidTokenError`, which the API layer renders as the single `401
UNAUTHENTICATED` problem of `openapi.yaml`. Re-reading the account on every request is what makes
deactivation effective immediately rather than at the token's next expiry.

The `role` claim is not trusted on its own: the authoritative role is the one on the persisted
account, so a token minted before a demotion cannot outlive it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.ports.token_service import InvalidTokenError, TokenService
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import UserRole
from app.domain.common.ids import UserId

__all__ = ["AuthenticatedUser", "authenticate_token"]


class AuthenticatedUser(BaseModel):
    """The caller of a request: who they are and what account role they hold (D8).

    It carries no credential — no digest, no token — so it is safe to log, attach to an event as
    an `ActorRef` or put in a problem document's `instance` trail (SPEC §41).
    """

    model_config = ConfigDict(frozen=True)

    user_id: UserId
    username: str
    display_name_ru: str
    user_role: UserRole

    @property
    def is_instructor_or_admin(self) -> bool:
        """True for the two roles `openapi.yaml` lets observe and command any session (D8)."""
        return self.user_role in (UserRole.INSTRUCTOR, UserRole.ADMIN)


async def authenticate_token(
    token: str, *, tokens: TokenService, unit_of_work: UnitOfWorkFactory
) -> AuthenticatedUser:
    """Resolve a bearer token to its account; raises `InvalidTokenError` for any unusable one."""
    claims = tokens.decode(token)
    async with unit_of_work() as uow:
        user = await uow.users.get(UserId(claims.subject))
        await uow.commit()
    if user is None or not user.is_active:
        raise InvalidTokenError("the token names an account that is unknown or deactivated")
    return AuthenticatedUser(
        user_id=user.user_id,
        username=user.username,
        display_name_ru=user.display_name_ru,
        # The persisted role wins over the `role` claim: a token minted before a demotion must
        # not outlive it (D8).
        user_role=user.user_role,
    )
