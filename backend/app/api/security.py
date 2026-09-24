"""Bearer-token authentication and the account-role gate (D8, SPEC §41).

Two dependencies and one helper:

* `get_current_user` — reads the `Authorization: Bearer …` header and resolves it through
  `app.application.auth.authenticate_token`. Every failure is one `InvalidTokenError`, which
  `app.api.errors` renders as `401 UNAUTHENTICATED` — `openapi.yaml` has exactly one `401` for
  every operation and distinguishing "no header" from "expired" would be an oracle;
* `require_roles(*roles)` — the account-role gate. It raises `ForbiddenForRoleError`, rendered as
  `403 FORBIDDEN_FOR_ROLE`, and it is D8's *account* gate only. The participant gate
  (`resolve_participant`) and the `RoleModule` gate belong to the command that fires a trigger,
  not to a dependency;
* `actor_of` — the `ActorRef` a use case stamps its events with (SPEC §8);
* `require_sip_gateway` (I3 E6e) — the SIP gateway's service credential on `/api/v1/telephony/*`:
  the `X-Sip-Gateway-Secret` header against `SIM_SIP_GATEWAY_SECRET`, never a user's token.

`HTTPBearer(auto_error=False)` is deliberate: FastAPI's own 401 would be a plain JSON body, not
`application/problem+json`, so the missing-header case is raised as our error and rendered by our
handler like every other one.

Nothing here logs a token, a header or a password (SPEC §41).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import ContainerDep
from app.application.auth.get_current_user import AuthenticatedUser, authenticate_token
from app.application.ports.token_service import InvalidTokenError
from app.application.ports.user_repository import UserRole
from app.application.sessions.queries import ForbiddenForRoleError
from app.domain.common.actors import ActorRef
from app.domain.enums import ActorType

__all__ = [
    "SIP_GATEWAY_SECRET_HEADER",
    "AdminOrInstructorDep",
    "CurrentUserDep",
    "SipGatewayDep",
    "actor_of",
    "bearer_scheme",
    "get_current_user",
    "require_roles",
    "require_sip_gateway",
]

bearer_scheme = HTTPBearer(auto_error=False, description="HS256 JWT minted by `loginUser` (D8).")
"""`auto_error=False` so a missing header becomes *our* problem+json, not Starlette's JSON."""


async def get_current_user(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> AuthenticatedUser:
    """The authenticated caller; raises `InvalidTokenError` (`401`) for every rejection."""
    if credentials is None or not credentials.credentials:
        raise InvalidTokenError("no bearer token")
    return await authenticate_token(
        credentials.credentials,
        tokens=container.tokens,
        unit_of_work=container.unit_of_work,
    )


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


def require_roles(
    *roles: UserRole,
) -> Callable[[AuthenticatedUser], Coroutine[Any, Any, AuthenticatedUser]]:
    """A dependency that admits only these account roles (`403 FORBIDDEN_FOR_ROLE`, D8).

    This is the *account* gate of D8 and nothing more. It never answers "may this user act on this
    session" — that is `resolve_participant` — and never "is this action available now" — that is
    the stage's `RoleModule`.
    """
    allowed = frozenset(roles)

    async def dependency(user: CurrentUserDep) -> AuthenticatedUser:
        if user.user_role not in allowed:
            names = ", ".join(sorted(role.value for role in allowed))
            raise ForbiddenForRoleError(f"this operation is permitted for {names} only")
        return user

    return dependency


AdminOrInstructorDep = Annotated[
    AuthenticatedUser, Depends(require_roles(UserRole.INSTRUCTOR, UserRole.ADMIN))
]
"""The gate `openapi.yaml` puts on `createSession`, `abortSession` and the scenario writes."""


SIP_GATEWAY_SECRET_HEADER = "X-Sip-Gateway-Secret"
"""`openapi.yaml`'s `sipGatewaySecret` security scheme (I3 E6e)."""

sip_gateway_scheme = APIKeyHeader(
    name=SIP_GATEWAY_SECRET_HEADER,
    auto_error=False,
    description="The SIP gateway's service credential, `SIM_SIP_GATEWAY_SECRET` (I3 E6e).",
)


async def require_sip_gateway(
    container: ContainerDep,
    secret: Annotated[str | None, Depends(sip_gateway_scheme)] = None,
) -> None:
    """Admit the SIP gateway only: the header equals `SIM_SIP_GATEWAY_SECRET` (I3 E6e, HLD 80
    §80.2.3). An unset secret refuses everything, so a deployment without the gateway exposes no
    telephony endpoint; every refusal is the one `401 UNAUTHENTICATED` (no oracle). The comparison
    is constant-time and nothing here logs the header (SPEC §41)."""
    expected = container.settings.sip_gateway_secret
    if not expected or not secret:
        raise InvalidTokenError("no SIP gateway credential")
    if not hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        raise InvalidTokenError("wrong SIP gateway credential")


SipGatewayDep = Annotated[None, Depends(require_sip_gateway)]
"""The gate on every `/api/v1/telephony/*` operation (`security: sipGatewaySecret`)."""


def actor_of(user: AuthenticatedUser) -> ActorRef:
    """The `ActorRef` a use case stamps this caller's events with (SPEC §8, §10.13).

    `ActorType` is the *simulation* actor taxonomy, not the account-role one: a `TRAINEE` account
    acts as `TRAINEE`, and both `INSTRUCTOR` and `ADMIN` act as `INSTRUCTOR` — the event log
    records who acted in the simulation, and an admin operating the console is acting as the
    instructor. `SIMULATION`, `MODEL` and `SYSTEM` are never a human caller.
    """
    actor_type = ActorType.TRAINEE if user.user_role is UserRole.TRAINEE else ActorType.INSTRUCTOR
    return ActorRef(actor_type=actor_type, actor_id=user.user_id)
