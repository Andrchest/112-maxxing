"""In-memory SIP registrar with Digest authentication (HLD 80 §80.2.1 `registrar.py`).

`REGISTER → 401 (nonce) → REGISTER(Digest) → 200`; `Expires: 0` unbinds; a wrong password is
`403`. Bindings are process memory: their loss costs a softphone one re-registration and nothing
else (INV 13 is untouched — no simulation state lives here).

**Credentials (I3 E6e, HLD 80 §80.7, D27).** Whose password a username has comes from a
`CredentialSource`:

* `AnyUserCredentials` — E6a's rule and the standalone gateway's (no backend configured): any
  username, the one deployment password `SIM_SIP_PASSWORD` ([credential redacted]);
* the backend's (`gateway.BackendCredentials`, over `GET /api/v1/telephony/sip-credentials/
  {username}`) — the username must be a `users.username` of an active account (**an unknown
  username is `403`**, E6e decision 3), and an account with its own `users.sip_ha1` is checked
  against that HA1 instead of the deployment password (migration `0015`).

The same nonce table and HA1 lookup check an INVITE's `Proxy-Authorization` (`verify_digest`), so
the gateway's `407` challenge (`SIM_SIP_INVITE_AUTH=challenge`) and REGISTER share one credential
rule. Every live binding is reported to `on_bind` / `on_unbind` — the gateway mirrors it to the
transient Redis key `sip:binding:{username}` (HLD 40 §40.6) the backend reads for the endpoint
choice (§80.3.7).

The clock is injected (`now`, seconds, monotonic by default) so expiry is tested without sleeping.
Nothing here logs a password, an HA1 or an `Authorization` header.
"""

from __future__ import annotations

import asyncio
import enum
import hmac
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from voice_agent.transport.sip.message import (
    SipMessage,
    build_challenge,
    build_response,
    digest_ha1,
    digest_response,
    new_tag,
    parse_auth_header,
    parse_name_addr,
    parse_uri,
)

__all__ = [
    "AnyUserCredentials",
    "Binding",
    "Credential",
    "CredentialSource",
    "CredentialUnavailableError",
    "DigestCheck",
    "Registrar",
]

logger = logging.getLogger(__name__)

DEFAULT_EXPIRES_S = 3600
MAX_EXPIRES_S = 3600
#: A nonce is accepted this long after it was issued; after that the UA gets `401 stale=true`.
NONCE_TTL_S = 300.0
_MAX_NONCES = 10_000


@dataclass(frozen=True)
class Binding:
    """One binding (§80.2.1: `{aor → (contact, transport, expires_at)}`).

    `channel` is where the REGISTER came from (the TCP connection, or the UDP peer): the gateway
    sends its own INVITE there when it rings this softphone (I3 E6e, click-to-call / `CALL_IN`)."""

    aor: str
    username: str
    contact: str
    transport: str
    source: tuple[str, int]
    expires_at: float
    channel: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Credential:
    """A known SIP user: its own HA1 (`users.sip_ha1`), or `None` ⇒ the deployment password."""

    ha1: str | None = field(default=None, repr=False)


class CredentialUnavailableError(RuntimeError):
    """The credential source cannot answer right now (the backend is unreachable): `503`."""


class CredentialSource(Protocol):
    """Who may register, and with which HA1 (see the module docstring)."""

    async def lookup(self, username: str) -> Credential | None:
        """The user's credential, or `None` for an unknown user (`403`)."""
        ...


class AnyUserCredentials:
    """E6a's rule: any username, the deployment password."""

    async def lookup(self, username: str) -> Credential | None:
        return Credential()


class DigestCheck(enum.Enum):
    """The verdict on one Digest `Authorization` / `Proxy-Authorization`."""

    OK = "OK"
    CHALLENGE = "CHALLENGE"  # no usable nonce: challenge (again)
    STALE = "STALE"  # the nonce expired: challenge with `stale=true`
    FORBIDDEN = "FORBIDDEN"  # wrong credential, wrong realm, unknown user
    UNAVAILABLE = "UNAVAILABLE"  # the credential source cannot answer


BindingHook = Callable[[Binding], Awaitable[None] | None]
UnbindHook = Callable[[str], Awaitable[None] | None]


class Registrar:
    """REGISTER handling and the binding table."""

    def __init__(
        self,
        *,
        realm: str,
        password: str,
        now: Callable[[], float] = time.monotonic,
        max_expires_s: int = MAX_EXPIRES_S,
        credentials: CredentialSource | None = None,
        on_bind: BindingHook | None = None,
        on_unbind: UnbindHook | None = None,
    ) -> None:
        if not password:
            raise ValueError("the registrar needs a deployment SIP password (SIM_SIP_PASSWORD)")
        self.realm = realm
        self._password = password
        self._now = now
        self._max_expires_s = max_expires_s
        self._credentials: CredentialSource = credentials or AnyUserCredentials()
        self._on_bind = on_bind
        self._on_unbind = on_unbind
        self._nonces: dict[str, float] = {}
        self._bindings: dict[str, Binding] = {}

    # -- bindings ---------------------------------------------------------------------------------

    def lookup(self, username: str) -> Binding | None:
        """The live binding of `username`, or `None` (an expired one is dropped here)."""
        binding = self._bindings.get(username)
        if binding is None:
            return None
        if binding.expires_at <= self._now():
            del self._bindings[username]
            # The Redis mirror expires by itself (same TTL); dropping it again is harmless.
            self._notify(self._on_unbind, username)
            return None
        return binding

    def is_registered(self, username: str | None) -> bool:
        return username is not None and self.lookup(username) is not None

    def bindings(self) -> list[Binding]:
        now = self._now()
        for username in [u for u, b in self._bindings.items() if b.expires_at <= now]:
            del self._bindings[username]
        return list(self._bindings.values())

    # -- Digest (REGISTER and INVITE) --------------------------------------------------------------

    def challenge_value(self, *, stale: bool = False) -> str:
        """A fresh `WWW-Authenticate` / `Proxy-Authenticate` value (nonce remembered)."""
        nonce = secrets.token_hex(16)
        self._remember_nonce(nonce)
        return build_challenge(self.realm, nonce, stale=stale)

    async def verify_digest(
        self, params: dict[str, str], *, method: str, expected_user: str | None = None
    ) -> tuple[DigestCheck, str | None]:
        """Check one Digest answer (`Authorization` or `Proxy-Authorization` params).

        Returns the verdict and the authenticated username (`OK` only). `expected_user`, when
        given, is the one username the answer may be for (the INVITE's From user, E6e decision 1).
        """
        nonce = params.get("nonce", "")
        issued = self._nonces.get(nonce)
        if issued is None:
            return DigestCheck.CHALLENGE, None
        if self._now() - issued > NONCE_TTL_S:
            del self._nonces[nonce]
            return DigestCheck.STALE, None
        username = params.get("username", "")
        if not username or params.get("realm") != self.realm:
            return DigestCheck.FORBIDDEN, None
        if expected_user is not None and username != expected_user:
            logger.info("%s refused: Digest user %s is not %s", method, username, expected_user)
            return DigestCheck.FORBIDDEN, None
        try:
            credential = await self._credentials.lookup(username)
        except CredentialUnavailableError:
            logger.warning("%s from %s: the credential source is unavailable", method, username)
            return DigestCheck.UNAVAILABLE, None
        if credential is None:
            logger.info("%s refused: unknown SIP user %s", method, username)
            return DigestCheck.FORBIDDEN, None
        ha1 = credential.ha1 or digest_ha1(username, self.realm, self._password)
        expected = digest_response(
            ha1,
            method=method,
            uri=params.get("uri", ""),
            nonce=nonce,
            qop=params.get("qop"),
            nc=params.get("nc"),
            cnonce=params.get("cnonce"),
        )
        if not hmac.compare_digest(expected, params.get("response", "")):
            logger.info("%s refused: wrong credential for user %s", method, username)
            return DigestCheck.FORBIDDEN, None
        return DigestCheck.OK, username

    # -- REGISTER ---------------------------------------------------------------------------------

    async def handle_register(
        self,
        request: SipMessage,
        *,
        source: tuple[str, int],
        transport: str,
        channel: Any = None,
    ) -> SipMessage:
        """The final response to one REGISTER (401 / 403 / 400 / 503 / 200)."""
        to_tag = new_tag()
        try:
            aor_uri = parse_uri(parse_name_addr(request.get("To") or "").uri)
        except ValueError:
            return build_response(request, 400, "Bad To", to_tag=to_tag)
        if not aor_uri.user:
            return build_response(request, 400, "No user in To", to_tag=to_tag)

        authorization = request.get("Authorization")
        if authorization is None:
            return self._challenge(request, to_tag)
        scheme, params = parse_auth_header(authorization)
        if scheme.lower() != "digest":
            return self._challenge(request, to_tag)
        verdict, username = await self.verify_digest(params, method="REGISTER")
        if verdict is DigestCheck.CHALLENGE:
            return self._challenge(request, to_tag)
        if verdict is DigestCheck.STALE:
            return self._challenge(request, to_tag, stale=True)
        if verdict is DigestCheck.UNAVAILABLE:
            return build_response(request, 503, "Credential service unavailable", to_tag=to_tag)
        if verdict is not DigestCheck.OK or username is None:
            return build_response(request, 403, "Forbidden", to_tag=to_tag)
        if username != aor_uri.user:
            logger.info("REGISTER refused: user %s tried to bind %s", username, aor_uri.user)
            return build_response(request, 403, "Forbidden", to_tag=to_tag)
        return self._bind(
            request, username, source=source, transport=transport, to_tag=to_tag, channel=channel
        )

    def _challenge(self, request: SipMessage, to_tag: str, *, stale: bool = False) -> SipMessage:
        return build_response(
            request,
            401,
            to_tag=to_tag,
            headers=[("WWW-Authenticate", self.challenge_value(stale=stale))],
        )

    def _remember_nonce(self, nonce: str) -> None:
        now = self._now()
        if len(self._nonces) >= _MAX_NONCES:
            self._nonces = {n: t for n, t in self._nonces.items() if now - t <= NONCE_TTL_S}
            while len(self._nonces) >= _MAX_NONCES:
                self._nonces.pop(next(iter(self._nonces)))
        self._nonces[nonce] = now

    def _bind(
        self,
        request: SipMessage,
        username: str,
        *,
        source: tuple[str, int],
        transport: str,
        to_tag: str,
        channel: Any = None,
    ) -> SipMessage:
        contacts = request.get_all("Contact")
        header_expires = _int_or_none(request.get("Expires"))
        if not contacts:  # a query: answer with the current binding, change nothing
            current = self.lookup(username)
            headers = [] if current is None else [("Contact", self._contact_header(current))]
            return build_response(request, 200, to_tag=to_tag, headers=headers)
        if contacts == ["*"]:
            if header_expires != 0:
                return build_response(request, 400, "Wildcard needs Expires: 0", to_tag=to_tag)
            self._bindings.pop(username, None)
            logger.info("REGISTER %s unbound (all)", username)
            self._notify(self._on_unbind, username)
            return build_response(request, 200, to_tag=to_tag)
        try:
            contact = parse_name_addr(contacts[0])
        except ValueError:
            return build_response(request, 400, "Bad Contact", to_tag=to_tag)
        expires = _int_or_none(contact.params.get("expires"))
        if expires is None:
            expires = header_expires if header_expires is not None else DEFAULT_EXPIRES_S
        if expires <= 0:
            self._bindings.pop(username, None)
            logger.info("REGISTER %s unbound", username)
            self._notify(self._on_unbind, username)
            return build_response(request, 200, to_tag=to_tag)
        expires = min(expires, self._max_expires_s)
        binding = Binding(
            aor=f"sip:{username}@{self.realm}",
            username=username,
            contact=contact.uri,
            transport=transport,
            source=source,
            expires_at=self._now() + expires,
            channel=channel,
        )
        self._bindings[username] = binding
        self._notify(self._on_bind, binding)
        logger.info(
            "REGISTER %s bound contact=%s via %s %s:%d expires=%ds",
            username,
            contact.uri,
            transport,
            source[0],
            source[1],
            expires,
        )
        return build_response(
            request,
            200,
            to_tag=to_tag,
            headers=[("Contact", self._contact_header(binding)), ("Expires", str(expires))],
        )

    @staticmethod
    def _notify(hook: Callable[[Any], Awaitable[None] | None] | None, value: Any) -> None:
        """Run a binding hook; a coroutine is scheduled, never awaited here (REGISTER never
        waits on the Redis mirror, and a failed mirror never fails a REGISTER)."""
        if hook is None:
            return
        try:
            result = hook(value)
        except Exception:
            logger.exception("SIP binding hook failed")
            return
        if result is not None and hasattr(result, "__await__"):
            try:
                task = asyncio.get_running_loop().create_task(result)  # type: ignore[arg-type]
            except RuntimeError:
                result.close()  # type: ignore[union-attr]
                return
            _HOOK_TASKS.add(task)
            task.add_done_callback(_HOOK_TASKS.discard)

    def _contact_header(self, binding: Binding) -> str:
        remaining = max(0, round(binding.expires_at - self._now()))
        return f"<{binding.contact}>;expires={remaining}"


_HOOK_TASKS: set[Any] = set()
"""Strong references to scheduled hook coroutines (asyncio keeps only weak ones)."""


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None
