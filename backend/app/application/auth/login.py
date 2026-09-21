"""`Login` — username + password → HS256 JWT (D8, SPEC §41).

Four readings, in this order, and only the last one is allowed to succeed:

1. no account with that username → `InvalidCredentialsError`;
2. the account exists but `is_active` is false → `InvalidCredentialsError`;
3. the digest does not verify → `InvalidCredentialsError`;
4. otherwise → a token for `(user_id, user_role)` plus the account itself.

The first three raise the **same** error with the same message. A login endpoint that
distinguished "no such user" from "wrong password" would be an account-enumeration oracle, and one
that distinguished "inactive" would leak that an account exists at all. `openapi.yaml` gives
`loginUser` exactly one `401`, so there is exactly one failure here.

The plaintext password is read once, handed to the `PasswordHasher` port and never stored, logged
or attached to an exception (SPEC §41). The digest is verified even for an unknown username, so
the request takes the same work either way and the response time is not an oracle either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.token_service import IssuedToken, TokenService
from app.application.ports.unit_of_work import UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser
from app.domain.common.errors import DomainError

__all__ = ["InvalidCredentialsError", "Login", "LoginCommand", "LoginResult"]

_DUMMY_DIGEST = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "c2ltMTEyLW5vdC1hLXJlYWwtc2FsdA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)
"""A well-shaped digest that matches nothing, verified when the username is unknown.

It is not a credential and unlocks nothing: `verify` against it always fails. Its only job is to
make the unknown-username path do the same KDF work as the known-username path, so the response
time does not reveal which usernames exist (SPEC §41).
"""


class InvalidCredentialsError(DomainError):
    """Wrong username, wrong password or an inactive account (`401 UNAUTHENTICATED`)."""

    code = "UNAUTHENTICATED"

    def __init__(self) -> None:
        super().__init__("invalid username or password")


@dataclass(frozen=True)
class LoginCommand:
    """`openapi.yaml`'s `LoginRequest`.

    `password` carries `repr=False` so neither a traceback frame nor a `repr()` of the command can
    print it (SPEC §41).
    """

    username: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class LoginResult:
    """What `loginUser` returns: the minted token and the account it belongs to."""

    token: IssuedToken
    user: StoredUser


class Login:
    """Verify a local account's password and mint its bearer token."""

    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        hasher: PasswordHasher,
        tokens: TokenService,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._hasher = hasher
        self._tokens = tokens

    async def __call__(self, command: LoginCommand) -> LoginResult:
        """Authenticate; raises `InvalidCredentialsError` for every rejected attempt."""
        async with self._unit_of_work() as uow:
            user = await uow.users.get_by_username(command.username)
            await uow.commit()

        digest = user.password_hash if user is not None else _DUMMY_DIGEST
        verified = self._hasher.verify(digest, command.password)
        if user is None or not user.is_active or not verified:
            raise InvalidCredentialsError()

        return LoginResult(token=self._tokens.issue(user.user_id, user.user_role), user=user)
