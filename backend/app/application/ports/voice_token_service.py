"""`VoiceTokenService` port — minting one room-scoped LiveKit access token (D9, `openapi.yaml`).

`createVoiceToken`: "The backend is the only minter of LiveKit tokens (D9): the frontend never
holds the LiveKit API secret. The token grants join on exactly the room of this session's active
call and nothing else."

A LiveKit access token is an ordinary HS256 JWT whose claims carry a `video` grant, so the backend
mints it with the `pyjwt` dependency it already has and **never imports the `livekit` SDK**: D2's
import table and `backend/tools/check_imports.py` keep `livekit` inside
`workers/voice_agent/voice_agent/transport/**`, which is the only place that speaks WebRTC.

The minted token is a credential: nothing in an implementation, in a use case or in a router logs
it (SPEC §41). Only the caller of `createVoiceToken` ever sees it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

__all__ = ["MintedVoiceToken", "VoiceTokenService"]


class MintedVoiceToken(BaseModel):
    """One minted token — `openapi.yaml`'s `VoiceTokenResponse`, property names literal."""

    model_config = ConfigDict(frozen=True)

    token: str
    livekit_url: str
    room_name: str
    participant_identity: str
    expires_at: datetime


@runtime_checkable
class VoiceTokenService(Protocol):
    """Mints a LiveKit access token scoped to exactly one room (D9)."""

    def mint(self, *, room_name: str, participant_identity: str) -> MintedVoiceToken:
        """A join token for `participant_identity` on `room_name`, and no other room.

        Synchronous on purpose: signing a JWT is CPU work with no I/O, and pretending otherwise
        would put an `await` in front of something that can never yield.
        """
        ...
