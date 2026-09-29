"""`auth` router — `loginUser`, `getCurrentUser` (`openapi.yaml`, D8, SPEC §41)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.audit import mark_recorded
from app.api.container import Container
from app.api.deps import ContainerDep
from app.api.schemas.auth import (
    LoginRequestSchema,
    TokenResponseSchema,
    UserAccountSchema,
    authenticated_user_schema,
    token_response_schema,
)
from app.api.security import CurrentUserDep
from app.application.auth.login import InvalidCredentialsError, LoginCommand, LoginResult
from app.application.auth.login_guard import LoginThrottledError
from app.application.ports.audit_log import AuditAction, AuditEntry, AuditOutcome
from app.application.ports.token_service import InvalidTokenError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    operation_id="loginUser",
    summary="Exchange username and password for a JWT.",
    response_model=TokenResponseSchema,
    status_code=200,
)
async def login_user(
    body: LoginRequestSchema, container: ContainerDep, request: Request
) -> TokenResponseSchema:
    """Verify a local account's password and mint its bearer token.

    `security: []` in `openapi.yaml`: this is the one operation that needs no token. Every
    rejection — unknown username, wrong password, inactive account — is the same
    `401 UNAUTHENTICATED`, and neither the password nor the minted token is ever logged.

    I4 E25: the attempt is audited here, not by the middleware, because it is unauthenticated —
    `LOGIN_SUCCEEDED` with the account, or `LOGIN_FAILED` with no user; the attempted username is
    `target_ids.username` and the password is never part of the entry.

    I7 E51 (G5, ТЗ ¶295): `LoginGuard.check` runs first — a throttled username or client IP never
    reaches `Login`, so it never pays the password hasher's work and never learns whether the
    password would have matched. A real failure feeds the guard's counters; a success clears the
    username's.
    """
    client_ip = request.client.host if request.client is not None else None
    guard = container.login_guard()
    try:
        await guard.check(username=body.username, client_ip=client_ip)
    except LoginThrottledError as exc:
        await _audit_login_throttled(request, container, body.username, exc)
        raise
    try:
        result = await container.login()(
            LoginCommand(username=body.username, password=body.password)
        )
    except InvalidCredentialsError:
        await guard.record_failure(username=body.username, client_ip=client_ip)
        await _audit_login(request, container, body.username, result=None)
        raise
    await guard.record_success(username=body.username)
    await _audit_login(request, container, body.username, result=result)
    return token_response_schema(result)


async def _audit_login(
    request: Request, container: Container, username: str, *, result: LoginResult | None
) -> None:
    """One `LOGIN_SUCCEEDED` / `LOGIN_FAILED` entry, and no middleware entry for this request."""
    succeeded = result is not None
    client = request.client
    await container.audit_recorder.record(
        AuditEntry(
            ts=container.clock.now(),
            action=AuditAction.LOGIN_SUCCEEDED if succeeded else AuditAction.LOGIN_FAILED,
            method=request.method,
            path_template=request.url.path,
            status=200 if succeeded else 401,
            outcome=AuditOutcome.OK if succeeded else AuditOutcome.DENIED,
            user_id=result.user.user_id if result is not None else None,
            role=result.user.user_role if result is not None else None,
            operation_id="loginUser",
            target_ids={"username": username},
            client_ip=client.host if client is not None else None,
        )
    )
    mark_recorded(request)


async def _audit_login_throttled(
    request: Request, container: Container, username: str, error: LoginThrottledError
) -> None:
    """One `LOGIN_THROTTLED` entry (I7 E51, G5) — no user, `429`, never the password."""
    client = request.client
    await container.audit_recorder.record(
        AuditEntry(
            ts=container.clock.now(),
            action=AuditAction.LOGIN_THROTTLED,
            method=request.method,
            path_template=request.url.path,
            status=429,
            outcome=AuditOutcome.DENIED,
            operation_id="loginUser",
            target_ids={"username": username, "retry_after_s": str(error.retry_after_s)},
            client_ip=client.host if client is not None else None,
        )
    )
    mark_recorded(request)


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
