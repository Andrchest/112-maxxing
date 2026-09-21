"""`createVoiceToken` over real HTTP — a real LiveKit JWT, and only for the right caller (D9).

The unit tests
(`backend/tests/unit/application/voice_token/test_create_voice_token.py`) own the decision table.
These own the wire: the status codes and problem codes `openapi.yaml` documents, the response
shape, and the fact that what comes back really is a token a LiveKit server would accept — decoded
here with `pyjwt` and the configured secret, not taken on trust.
"""

from __future__ import annotations

import jwt
import pytest
from app.api.container import Container
from app.application.auth.get_current_user import AuthenticatedUser
from app.application.ports.user_repository import UserRole
from app.config.settings import Settings
from app.domain.common.ids import SessionId

from tests.api._openapi import load_openapi, operation_of
from tests.api.conftest import auth
from tests.api.voice.conftest import OperatorFlow

pytestmark = pytest.mark.integration


async def token_of(flow: OperatorFlow, **kwargs: str) -> dict[str, object]:
    """`POST /voice-token` as the operator trainee; asserts 200 and returns the body."""
    response = await flow.post("/voice-token", **kwargs)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


# -- the happy path --------------------------------------------------------------------------------


async def test_a_ringing_call_yields_a_valid_livekit_jwt(
    ringing: OperatorFlow, container: Container, api_settings: Settings
) -> None:
    body = await token_of(ringing)

    claims = jwt.decode(str(body["token"]), api_settings.livekit_api_secret, algorithms=["HS256"])
    assert claims["iss"] == api_settings.livekit_api_key
    assert claims["sub"] == str(ringing.operator_user_id)
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == body["room_name"]
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is True
    assert "exp" in claims


async def test_the_response_has_exactly_the_five_contract_properties(
    ringing: OperatorFlow,
) -> None:
    body = await token_of(ringing)

    assert set(body) == {
        "token",
        "livekit_url",
        "room_name",
        "participant_identity",
        "expires_at",
    }
    assert body["participant_identity"] == str(ringing.operator_user_id)


async def test_the_room_is_the_one_call_ringing_named(ringing: OperatorFlow) -> None:
    """The token grants the room of *this session's* call, not a room the client chose."""
    snapshot = await ringing.snapshot()
    call_state = snapshot.json()["call_state"]

    body = await token_of(ringing)

    assert body["room_name"] == call_state["room_name"]
    assert body["room_name"] == f"session-{ringing.session_id}"


async def test_a_connected_call_still_mints(connected: OperatorFlow) -> None:
    body = await token_of(connected)

    assert body["room_name"] == f"session-{connected.session_id}"


# -- the browser-facing URL ------------------------------------------------------------------------


async def test_livekit_url_is_the_browser_facing_url_when_one_is_configured(
    ringing: OperatorFlow, api_settings: Settings
) -> None:
    """A container-internal host name does not resolve in the trainee's browser (E11 ruling).

    `SIM_LIVEKIT_PUBLIC_URL` is what the response carries; `SIM_LIVEKIT_URL` stays the URL this
    process and the voice-agent dial. The two are asserted to be genuinely different here so the
    test would fail if the response ever went back to echoing the internal one.
    """
    internal = "ws://livekit-internal.invalid:7880"
    browser = "ws://localhost:7880"
    assert internal != browser
    settings = api_settings.model_copy(
        update={"livekit_url": internal, "livekit_public_url": browser}
    )

    container = Container(
        settings,
        engine=ringing.container.engine,
        session_factory=ringing.container.session_factory,
        redis=ringing.container.redis,
        publisher=ringing.container.publisher,
        unit_of_work=ringing.container.unit_of_work,
        hasher=ringing.container.hasher,
        inference=ringing.container.inference,
        owns_engine=False,
        owns_redis=False,
    )

    minted = await container.create_voice_token()(
        SessionId(ringing.session_id), _authenticated(ringing)
    )

    assert minted.livekit_url == browser
    assert minted.livekit_url != internal


def _authenticated(flow: OperatorFlow) -> AuthenticatedUser:
    """The operator trainee as the application layer sees them."""
    return AuthenticatedUser(
        user_id=flow.operator_user_id,
        username="trainee1",
        display_name_ru="Стажёр",
        user_role=UserRole.TRAINEE,
        is_active=True,
    )


async def test_livekit_url_defaults_to_the_process_url_when_no_public_url_is_set(
    ringing: OperatorFlow, api_settings: Settings
) -> None:
    body = await token_of(ringing)

    assert api_settings.livekit_public_url == ""
    assert body["livekit_url"] == api_settings.livekit_url


# -- the refusals ---------------------------------------------------------------------------------


async def test_before_the_call_rings_there_is_nothing_to_join(flow: OperatorFlow) -> None:
    response = await flow.post("/voice-token")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_after_the_call_ends_the_room_is_not_re_enterable(
    connected: OperatorFlow,
) -> None:
    ended = await connected.post("/operator/call/end", json={"reason": "OPERATOR_HANGUP"})
    assert ended.status_code == 200, ended.text

    response = await connected.post("/voice-token")

    assert response.status_code == 409
    assert response.json()["code"] == "ACTION_NOT_AVAILABLE"


async def test_another_trainee_is_not_a_participant_of_this_stage(
    ringing: OperatorFlow,
) -> None:
    response = await ringing.post("/voice-token", token=ringing.dds_token)

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_FOR_ROLE"


async def test_the_instructor_gets_no_token(ringing: OperatorFlow) -> None:
    """An instructor observes the call; they do not join it (SPEC §7)."""
    response = await ringing.post("/voice-token", token=ringing.instructor_token)

    assert response.status_code == 403
    assert response.json()["code"] in {"PARTICIPANT_NOT_ASSIGNED", "FORBIDDEN_FOR_ROLE"}


async def test_an_anonymous_caller_is_unauthenticated(ringing: OperatorFlow) -> None:
    response = await ringing.client.post(ringing.url("/voice-token"))

    assert response.status_code == 401


async def test_an_unknown_session_is_404(ringing: OperatorFlow) -> None:
    response = await ringing.client.post(
        "/api/v1/sessions/00000000-0000-4000-8000-000000000000/voice-token",
        headers=auth(ringing.operator_token),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_an_aborted_session_mints_nothing(ringing: OperatorFlow) -> None:
    aborted = await ringing.client.post(
        ringing.url("/abort"),
        headers=auth(ringing.instructor_token),
        json={"reason": "instructor stopped the exercise"},
    )
    assert aborted.status_code == 200, aborted.text

    response = await ringing.post("/voice-token")

    assert response.status_code == 409
    assert response.json()["code"] == "SESSION_NOT_ACTIVE"


# -- SPEC §41: a credential is not log material ----------------------------------------------------


async def test_the_token_is_never_logged(
    ringing: OperatorFlow, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        body = await token_of(ringing)

    token = str(body["token"])
    assert token not in caplog.text
    # The secret has no business in a log line either.
    for record in caplog.records:
        assert "devsecret" not in record.getMessage()


async def test_create_voice_token_emits_exactly_its_x_emits(ringing: OperatorFlow) -> None:
    """`openapi.yaml` declares `x-emits: []`, and minting appends nothing — one statement."""
    operation = operation_of(load_openapi(), "/api/v1/sessions/{session_id}/voice-token", "post")
    assert operation is not None
    assert operation["x-emits"] == []

    before = await ringing.event_types()
    assert (await ringing.post("/voice-token")).status_code == 200

    assert await ringing.event_types() == before
