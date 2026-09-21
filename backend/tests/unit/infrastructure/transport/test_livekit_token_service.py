"""`LiveKitTokenService` — the token really is a LiveKit JWT, and it grants one room (D9, §41).

These tests decode what the adapter produced with `pyjwt` and the same secret, because "it is a
valid LiveKit access token" is a claim about bytes, not about an object this module returned.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from app.infrastructure.transport.livekit_token_service import (
    ALGORITHM,
    LiveKitTokenService,
)

SECRET = "test-only-livekit-secret-0123456789abcdef"
KEY = "test-key"


def service(
    ttl_minutes: int = 10, livekit_url: str = "ws://livekit.test:7880"
) -> LiveKitTokenService:
    """The adapter under test, with test-only credentials."""
    return LiveKitTokenService(KEY, SECRET, livekit_url=livekit_url, ttl_minutes=ttl_minutes)


def decode(token: str) -> dict[str, object]:
    """Decode with the same secret the adapter signed with."""
    claims: dict[str, object] = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    return claims


def test_the_token_is_a_valid_hs256_jwt_carrying_a_video_grant() -> None:
    minted = service().mint(room_name="session-abc", participant_identity="user-1")

    claims = decode(minted.token)

    assert claims["iss"] == KEY
    assert claims["sub"] == "user-1"
    assert claims["video"] == {
        "roomJoin": True,
        "room": "session-abc",
        "canPublish": True,
        "canSubscribe": True,
    }


def test_the_grant_names_one_room_and_no_admin_capability() -> None:
    """`openapi.yaml`: "grants join on exactly the room of this session's active call"."""
    grant = decode(service().mint(room_name="session-abc", participant_identity="u").token)["video"]

    assert isinstance(grant, dict)
    assert grant["room"] == "session-abc"
    for forbidden in ("roomCreate", "roomList", "roomAdmin", "roomRecord", "hidden", "recorder"):
        assert forbidden not in grant


def test_exp_is_the_configured_ttl_and_the_response_agrees_with_the_claim() -> None:
    minted = service(ttl_minutes=3).mint(room_name="r", participant_identity="u")

    claims = decode(minted.token)
    exp = claims["exp"]
    iat = claims["iat"]

    assert isinstance(exp, int) and isinstance(iat, int)
    assert exp - iat == 3 * 60
    assert int(minted.expires_at.timestamp()) == exp
    assert minted.expires_at > datetime.now(UTC)


def test_a_wrong_secret_does_not_verify() -> None:
    """The secret is what makes the token a credential; a token anyone can forge is not one."""
    minted = service().mint(room_name="r", participant_identity="u")

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(minted.token, "another-secret-entirely-0123456789", algorithms=[ALGORITHM])


def test_the_response_carries_the_browser_facing_url_it_was_built_with() -> None:
    minted = service(livekit_url="ws://localhost:7880").mint(
        room_name="r", participant_identity="u"
    )

    assert minted.livekit_url == "ws://localhost:7880"
    assert minted.room_name == "r"
    assert minted.participant_identity == "u"


def test_empty_credentials_are_refused_at_construction() -> None:
    """A token signed with no secret is not a token; failing here beats failing at the SFU."""
    with pytest.raises(ValueError, match="SIM_LIVEKIT_API_KEY"):
        LiveKitTokenService("", SECRET, livekit_url="ws://x", ttl_minutes=10)
    with pytest.raises(ValueError, match="SIM_LIVEKIT_API_SECRET"):
        LiveKitTokenService(KEY, "", livekit_url="ws://x", ttl_minutes=10)
