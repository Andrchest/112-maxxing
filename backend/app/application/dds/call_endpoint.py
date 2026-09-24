"""Where the trainee's side of a ДДС call is — `BROWSER` or `SIP` (I3 E6e, HLD `80-telephony.md`
§80.3.7, D25).

Not a variant switch and not a `SIM_CALL_TRANSPORT` value (D25): the endpoint is chosen per call, at
its `start`, and recorded on `DDS_CALL_STARTED.endpoint` (P4). The rule is one line — if the
deployment allows the softphone endpoint (`SIM_TELEPHONY_ENDPOINTS` contains `sip`) and the
trainee's user has a live registration (`sip:binding:{username}`), the call is `SIP`; otherwise it
is `BROWSER`. A softphone-*dialled* call is `SIP` by construction and never asks.

Losing the binding (a Redis flush, an expired key, the softphone switched off) therefore changes
nothing but where the next call rings: the browser widget, until the softphone's next REGISTER
refresh writes the key again. No simulation state is involved.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.application.ports.sip_bindings import SipBindingDirectory
from app.domain.dds.call import CallEndpoint

__all__ = ["BROWSER_ONLY", "SIP_ENDPOINT_NAME", "CallEndpointChooser"]

SIP_ENDPOINT_NAME = "sip"
"""The `SIM_TELEPHONY_ENDPOINTS` entry that enables the softphone endpoint."""


class CallEndpointChooser:
    """§80.3.7's endpoint rule, over the gateway's mirrored registrations."""

    def __init__(
        self, bindings: SipBindingDirectory | None, endpoints: Iterable[str] = ("browser",)
    ) -> None:
        self._bindings = bindings
        self._sip_enabled = SIP_ENDPOINT_NAME in {item.strip().lower() for item in endpoints}

    @property
    def sip_enabled(self) -> bool:
        """The deployment allows the softphone endpoint at all."""
        return self._sip_enabled and self._bindings is not None

    async def choose(self, username: str | None) -> CallEndpoint:
        """`SIP` for a user with a live softphone registration, else `BROWSER`."""
        if not self.sip_enabled or not username or self._bindings is None:
            return CallEndpoint.BROWSER
        if await self._bindings.is_bound(username):
            return CallEndpoint.SIP
        return CallEndpoint.BROWSER


BROWSER_ONLY = CallEndpointChooser(None)
"""The chooser of a deployment without the softphone endpoint (every call is `BROWSER`)."""
