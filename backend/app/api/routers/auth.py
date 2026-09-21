"""`auth` router — `loginUser`, `getCurrentUser` (`openapi.yaml`, D8, SPEC §41)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.api.schemas.auth import (
    LoginRequestSchema,
    TokenResponseSchema,
    UserAccountSchema,
    authenticated_user_schema,
    token_response_schema,
)
from app.api.security import CurrentUserDep
from app.application.auth.login import LoginCommand
from app.application.ports.token_service import InvalidTokenError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    operation_id="loginUser",
    summary="Exchange username and password for a JWT.",
    response_model=TokenResponseSchema,
    status_code=200,
)
async def login_user(body: LoginRequestSchema, container: ContainerDep) -> TokenResponseSchema:
    """Verify a local account's password and mint its bearer token.

    `security: []` in `openapi.yaml`: this is the one operation that needs no token. Every
    rejection — unknown username, wrong password, inactive account — is the same
    `401 UNAUTHENTICATED`, and neither the password nor the minted token is ever logged.
    """
    result = await container.login()(LoginCommand(username=body.username, password=body.password))
    return token_response_schema(result)


@router.get(
    "/me",
    operation_id="getCurrentUser",
    summary="The authenticated user account.",
    response_model=UserAccountSchema,
    status_code=200,
)
async def get_current_user_account(
    user: CurrentUserDep, container: ContainerDep
) -> UserAccountSchema:
    """The account the bearer token names.

    `AuthenticatedUser` carries no `created_at` — it is an authorisation value, not a profile — so
    the account row is read here for that one field.
    """
    async with container.unit_of_work() as uow:
        account = await uow.users.get(user.user_id)
        await uow.commit()
    if account is None:  # pragma: no cover - `authenticate_token` just read the same row
        raise InvalidTokenError("the token names an account that is unknown or deactivated")
    return authenticated_user_schema(user, account.created_at)
