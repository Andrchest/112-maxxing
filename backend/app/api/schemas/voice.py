"""`voice` schemas — `VoiceTokenResponse` (`openapi.yaml`, D9).

One model, five properties, all required, `additionalProperties: false` — the contract's, literally.
`token` is a credential: it is serialised into exactly one response body and is never logged, never
echoed into a problem detail and never cached (SPEC §41).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.api.schemas.common import ApiModel
from app.application.ports.voice_token_service import MintedVoiceToken

__all__ = ["VoiceTokenRequestSchema", "VoiceTokenResponseSchema", "voice_token_response_schema"]


class VoiceTokenRequestSchema(ApiModel):
    """`openapi.yaml`'s `VoiceTokenRequest` (additive, I3 E6b): the ДДС call whose room to join;
    absent ⇒ the session's 112 call, as before."""

    call_id: UUID | None = None


class VoiceTokenResponseSchema(ApiModel):
    """`openapi.yaml`'s `VoiceTokenResponse`, property names literal."""

    token: str
    livekit_url: str
    room_name: str
    participant_identity: str
    expires_at: datetime


def voice_token_response_schema(minted: MintedVoiceToken) -> VoiceTokenResponseSchema:
    """`MintedVoiceToken` -> the wire model (D2: the mapping is explicit, never a passthrough)."""
    return VoiceTokenResponseSchema(
        token=minted.token,
        livekit_url=minted.livekit_url,
        room_name=minted.room_name,
        participant_identity=minted.participant_identity,
        expires_at=minted.expires_at,
    )
