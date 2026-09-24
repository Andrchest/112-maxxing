"""In-memory SIP registrar with Digest authentication (HLD 80 §80.2.1 `registrar.py`).

`REGISTER → 401 (nonce) → REGISTER(Digest) → 200`; `Expires: 0` unbinds; a wrong password is
`403`. In E6a the credential is *any* username with the one deployment password
`SIM_SIP_PASSWORD` ([credential redacted] in every document); E6e checks the username against
`users.username` and may switch to per-user HA1 (80 §80.7, `0014`). Bindings are process memory:
their loss costs a softphone one re-registration and nothing else (INV 13 is untouched — no
simulation state lives here).

The clock is injected (`now`, seconds, monotonic by default) so expiry is tested without sleeping.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

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

__all__ = ["Binding", "Registrar"]

logger = logging.getLogger(__name__)

DEFAULT_EXPIRES_S = 3600
MAX_EXPIRES_S = 3600
#: A nonce is accepted this long after it was issued; after that the UA gets `401 stale=true`.
NONCE_TTL_S = 300.0
_MAX_NONCES = 10_000


@dataclass(frozen=True)
class Binding:
    """One binding (§80.2.1: `{aor → (contact, transport, expires_at)}`)."""

    aor: str
    username: str
    contact: str
    transport: str
    source: tuple[str, int]
    expires_at: float


class Registrar:
    """REGISTER handling and the binding table."""

    def __init__(
        self,
        *,
        realm: str,
        password: str,
        now: Callable[[], float] = time.monotonic,
        max_expires_s: int = MAX_EXPIRES_S,
    ) -> None:
        if not password:
            raise ValueError("the registrar needs a deployment SIP password (SIM_SIP_PASSWORD)")
        self.realm = realm
        self._password = password
        self._now = now
        self._max_expires_s = max_expires_s
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
            return None
        return binding

    def is_registered(self, username: str | None) -> bool:
        return username is not None and self.lookup(username) is not None

    def bindings(self) -> list[Binding]:
        now = self._now()
        for username in [u for u, b in self._bindings.items() if b.expires_at <= now]:
            del self._bindings[username]
        return list(self._bindings.values())

    # -- REGISTER ---------------------------------------------------------------------------------

    def handle_register(
        self, request: SipMessage, *, source: tuple[str, int], transport: str
    ) -> SipMessage:
        """The final response to one REGISTER (401 / 403 / 400 / 200)."""
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
        nonce = params.get("nonce", "")
        issued = self._nonces.get(nonce)
        if issued is None:
            return self._challenge(request, to_tag)
        if self._now() - issued > NONCE_TTL_S:
            del self._nonces[nonce]
            return self._challenge(request, to_tag, stale=True)
        username = params.get("username", "")
        if not username or params.get("realm") != self.realm:
            return build_response(request, 403, "Forbidden", to_tag=to_tag)
        expected = digest_response(
            digest_ha1(username, self.realm, self._password),
            method="REGISTER",
            uri=params.get("uri", ""),
            nonce=nonce,
            qop=params.get("qop"),
            nc=params.get("nc"),
            cnonce=params.get("cnonce"),
        )
        if not hmac.compare_digest(expected, params.get("response", "")):
            logger.info("REGISTER refused: wrong credential for user %s", username)
            return build_response(request, 403, "Forbidden", to_tag=to_tag)
        if username != aor_uri.user:
            logger.info("REGISTER refused: user %s tried to bind %s", username, aor_uri.user)
            return build_response(request, 403, "Forbidden", to_tag=to_tag)
        return self._bind(request, username, source=source, transport=transport, to_tag=to_tag)

    def _challenge(self, request: SipMessage, to_tag: str, *, stale: bool = False) -> SipMessage:
        nonce = secrets.token_hex(16)
        self._remember_nonce(nonce)
        return build_response(
            request,
            401,
            to_tag=to_tag,
            headers=[("WWW-Authenticate", build_challenge(self.realm, nonce, stale=stale))],
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
            return build_response(request, 200, to_tag=to_tag)
        expires = min(expires, self._max_expires_s)
        binding = Binding(
            aor=f"sip:{username}@{self.realm}",
            username=username,
            contact=contact.uri,
            transport=transport,
            source=source,
            expires_at=self._now() + expires,
        )
        self._bindings[username] = binding
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

    def _contact_header(self, binding: Binding) -> str:
        remaining = max(0, round(binding.expires_at - self._now()))
        return f"<{binding.contact}>;expires={remaining}"


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None
