"""`RedisSipBindings` — the `sip:binding:{username}` key over Redis (I3 E6e, HLD 40 §40.6,
HLD `80-telephony.md` §80.3.7).

Two sides of one key:

* `is_bound` — the backend's read, at the `start` of a ДДС call (the endpoint choice);
* `bind` / `unbind` — the SIP gateway's writes, on every successful REGISTER (`SET … EX
  <Expires>`, value `{contact, expires_at}`) and on an unregister or an expiry.

None of them raises: the key is transient, and an unreachable Redis means "no softphone" to the
reader and a lost mirror to the writer — the next REGISTER refresh writes it again (§40.6).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.ports.sip_bindings import sip_binding_key

__all__ = ["RedisSipBindings"]

logger = logging.getLogger(__name__)


class RedisSipBindings:
    """`SipBindingDirectory` (and the gateway's writer) over `redis.asyncio`."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def is_bound(self, username: str) -> bool:
        try:
            return bool(await self._client.exists(sip_binding_key(username)))
        except Exception:  # transient state: an unreachable Redis reads as "no binding"
            logger.warning("could not read the SIP binding of %s; assuming none", username)
            return False

    async def bind(self, username: str, *, contact: str, expires_at: float, ttl_s: int) -> None:
        """Mirror one live registration for `ttl_s` seconds (its `Expires`)."""
        payload = json.dumps({"contact": contact, "expires_at": expires_at})
        try:
            await self._client.set(sip_binding_key(username), payload, ex=max(1, int(ttl_s)))
        except Exception:
            logger.warning("could not mirror the SIP binding of %s", username)

    async def unbind(self, username: str) -> None:
        """Drop the mirror of `username`'s registration (unregister or expiry)."""
        try:
            await self._client.delete(sip_binding_key(username))
        except Exception:
            logger.warning("could not drop the SIP binding mirror of %s", username)
