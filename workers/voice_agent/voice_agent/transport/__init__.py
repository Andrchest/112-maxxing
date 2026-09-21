"""Call transport adapters.

The only package allowed to import the `livekit` SDK (D9, D2): `LiveKitCallTransport` lives here,
behind the application-layer `CallTransport` port. Still forbidden: `openai`, `anthropic`.
"""

from __future__ import annotations

from voice_agent.transport.sip_transport import SipCallTransport

__all__ = ["SipCallTransport"]
