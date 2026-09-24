"""`SipBindingDirectory` port — "does this trainee have a live softphone?" (I3 E6e, HLD
`80-telephony.md` §80.3.7, HLD 40 §40.6 `sip:binding:{username}`).

The SIP gateway's registrar keeps its bindings in process memory and mirrors each live one to the
transient Redis key `sip:binding:{username}` (value `{contact, expires_at}`, `EX` = the binding's
`Expires`), deleting it on unregister. The backend reads that key at the `start` of a ДДС call to
choose the call's endpoint: a live registration wins (`SIP`), anything else is `BROWSER`.

The key is never a source of truth: its loss only sends the next call to the browser widget until
the softphone's next REGISTER refresh; no simulation state is involved (INV 13). An implementation
therefore never raises — an unreachable Redis reads as "no binding".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["SIP_BINDING_KEY_PREFIX", "SipBindingDirectory", "sip_binding_key"]

SIP_BINDING_KEY_PREFIX = "sip:binding:"


def sip_binding_key(username: str) -> str:
    """`sip:binding:{username}` — HLD 40 §40.6's key, the SIP username being `users.username`."""
    return f"{SIP_BINDING_KEY_PREFIX}{username}"


@runtime_checkable
class SipBindingDirectory(Protocol):
    """Read the gateway's mirrored registrations."""

    async def is_bound(self, username: str) -> bool:
        """`True` while `sip:binding:{username}` exists (a live softphone registration)."""
        ...
