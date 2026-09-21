"""`LiveKitTokenService` — the backend mints LiveKit access tokens itself (D9, SPEC §41).

A LiveKit access token is a plain HS256 JWT: `iss` is the API key, `sub`/`identity` is the
participant, `exp` bounds it, and the LiveKit-specific part is one `video` claim carrying the
grant. Nothing about that needs the `livekit` SDK, so this module signs it with the `pyjwt`
dependency the backend already has — which is what keeps `livekit` confined to
`workers/voice_agent/voice_agent/transport/**` (D2, `backend/tools/check_imports.py`).

The grant is deliberately the smallest one a call needs (`openapi.yaml`: "The token grants join on
exactly the room of this session's active call and nothing else"):

* `roomJoin: true`, `room: <this session's room>` — join that room, no other;
* `canPublish: true`, `canSubscribe: true` — a call is two-way audio;
* no `roomCreate`, no `roomAdmin`, no `roomList`, no `canPublishData`, no `hidden`, no `recorder`.

The secret and the minted token are never logged (SPEC §41): nothing in this module writes a log
line, and `MintedVoiceToken` is returned to exactly one caller.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.application.ports.voice_token_service import MintedVoiceToken

__all__ = ["ALGORITHM", "LiveKitTokenService"]

ALGORITHM = "HS256"
"""LiveKit signs access tokens with HS256 over the API secret."""


class LiveKitTokenService:
    """`VoiceTokenService` over PyJWT — see this module's docstring for the grant."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        livekit_url: str,
        ttl_minutes: int,
        algorithm: str = ALGORITHM,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError(
                "SIM_LIVEKIT_API_KEY / SIM_LIVEKIT_API_SECRET are empty; a LiveKit token signed "
                "with no credentials is not one"
            )
        self._api_key = api_key
        self._api_secret = api_secret
        self._livekit_url = livekit_url
        self._ttl = timedelta(minutes=ttl_minutes)
        self._algorithm = algorithm

    def mint(self, *, room_name: str, participant_identity: str) -> MintedVoiceToken:
        """A join token for `participant_identity` on `room_name`, valid for the configured TTL."""
        issued_at = datetime.now(UTC)
        expires_at = issued_at + self._ttl
        claims: dict[str, Any] = {
            "iss": self._api_key,
            "sub": participant_identity,
            "name": participant_identity,
            "nbf": int(issued_at.timestamp()),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "video": {
                "roomJoin": True,
                "room": room_name,
                "canPublish": True,
                "canSubscribe": True,
            },
        }
        token = jwt.encode(claims, self._api_secret, algorithm=self._algorithm)
        return MintedVoiceToken(
            token=token,
            livekit_url=self._livekit_url,
            room_name=room_name,
            participant_identity=participant_identity,
            expires_at=expires_at,
        )
