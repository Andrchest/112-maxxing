"""The SIP endpoint wired to the domain — the backend half (I3 E6e, HLD `80-telephony.md` §80.2.3,
§80.3.5, §80.3.7, §80.7; the E6e row of HLD 90).

The real use cases on fakes (`FakeCallTransportStatus`, `InMemoryVoiceSignals`,
`InMemorySipBindings`, the movable `FakeClock`; no GPU, no network), over real HTTP and a real
database, exactly as the SIP gateway calls them (`X-Sip-Gateway-Secret`):

* `dialFromSip` dials `101` / `7xxx` / `112` / the claimant's digits into `startDdsCall` with the
  `SIP` endpoint; an unknown number is `404 DIAL_NUMBER_UNKNOWN`, no eligible session `409
  NO_ACTIVE_DDS_SESSION`, an unknown user `403`;
* the session selection — the card this user opened last wins, else the oldest;
* `reportSipLeg`: `UP` rings (and the AI answers on the tick), `DOWN` ⇒ `hang_up` TRAINEE,
  `FAILED` ⇒ SYSTEM `ABORT`, a late report on an `ENDED` call is ignored, a `BROWSER` call is 409;
* the endpoint choice: a live `sip:binding:{username}` makes the browser button's call `SIP`
  (`voice:join {endpoint: SIP, sip_user}` at once, no browser token); its loss ⇒ `BROWSER`;
* a brigade's `CALL_IN` rings the softphone, and the gateway's `leg UP` is the trainee's answer;
* `getSipCredential` (migration `0015`): `403` unknown, `404` none, `200` the HA1;
* the gateway's service credential gates every telephony operation.

The throwaway `GATEWAY_SECRET` below is a TEST FIXTURE, not a credential of any deployment.
"""

# The E6b/E6c suites' fixtures are imported and requested by name (pytest), which ruff reads as a
# redefinition: F811 is expected throughout this file.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import pytest
from app.api.container import Container
from app.application.telephony.dial_from_sip import SessionCandidate, select_dds_session
from app.application.testing.fakes import (
    FakeCallTransportStatus,
    FakeClock,
    FakeInferenceReadiness,
    FakePasswordHasher,
    InMemoryEventPublisher,
    InMemoryIdempotencyStore,
    InMemorySipBindings,
    InMemoryVoiceSignals,
    StubVoiceTokenService,
)
from app.config.settings import Settings
from app.db.session import create_session_factory
from app.domain.common.ids import ScenarioVersionId, SessionId, UserId
from app.domain.dds.call import CallSelectionReason
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory
from app.tools.set_sip_password import sip_ha1
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.dds.test_dds_calls import (  # noqa: F401
    ANSWER_AFTER_MS,
    API,
    CLAIMANT_DIGITS,
    dds,
    get_call,
    of_type,
    off_session,
    on_session,
    rubbish_version_id,
    start_claimant_call,
    started_session,
    tick,
    transport,
    voice_signals,
    voice_tokens,
)
from tests.api.dds.test_service_head_calls import call_in_version_id, legs  # noqa: F401

pytestmark = pytest.mark.integration

#: TEST FIXTURE ONLY — the gateway's service credential in this suite, never a real secret.
GATEWAY_SECRET = "test-fixture-sip-gateway-secret-not-a-secret"
TELEPHONY = "/api/v1/telephony"
SIP_USER = "trainee2"


def gateway() -> dict[str, str]:
    return {"X-Sip-Gateway-Secret": GATEWAY_SECRET}


@pytest.fixture
def sip_bindings() -> InMemorySipBindings:
    return InMemorySipBindings()


@pytest.fixture
def container(
    api_settings: Settings,
    migrated_engine: AsyncEngine,
    redis_client: Redis,
    publisher: InMemoryEventPublisher,
    hasher: FakePasswordHasher,
    inference: FakeInferenceReadiness,
    idempotency: InMemoryIdempotencyStore,
    clock: FakeClock,
    transport: FakeCallTransportStatus,
    voice_signals: InMemoryVoiceSignals,
    voice_tokens: StubVoiceTokenService,
    sip_bindings: InMemorySipBindings,
) -> Container:
    """The E6b suite's container, with the softphone endpoint enabled and the gateway's secret."""
    settings = api_settings.model_copy(
        update={
            "sip_gateway_secret": GATEWAY_SECRET,
            "telephony_endpoints": "browser,sip",
            "sip_realm": "sim112-test",
        }
    )
    session_factory = create_session_factory(migrated_engine)
    return Container(
        settings,
        engine=migrated_engine,
        session_factory=session_factory,
        redis=redis_client,
        publisher=publisher,
        clock=clock,
        unit_of_work=unit_of_work_factory(session_factory, clock, publisher),
        hasher=hasher,
        inference=inference,
        idempotency=idempotency,
        call_transport_status=transport,
        voice_signals=voice_signals,
        voice_tokens=voice_tokens,
        sip_bindings=sip_bindings,
        owns_engine=False,
        owns_redis=False,
    )


async def dial(client: httpx.AsyncClient, dialed: str, sip_user: str = SIP_USER) -> httpx.Response:
    return await client.post(
        f"{TELEPHONY}/dial",
        headers=gateway(),
        json={"sip_user": sip_user, "dialed": dialed, "sip_call_id": "abc123@127.0.0.1"},
    )


async def leg(
    client: httpx.AsyncClient, call_id: str, state: str, sip_status: int | None = None
) -> httpx.Response:
    return await client.post(
        f"{TELEPHONY}/calls/{call_id}/leg",
        headers=gateway(),
        json={"state": state, **({"sip_status": sip_status} if sip_status else {})},
    )


async def started_payload(
    client: httpx.AsyncClient, tokens: dict[str, str], session_id: UUID, call_id: str
) -> dict[str, Any]:
    for item in await of_type(client, tokens, session_id, "DDS_CALL_STARTED"):
        if item["payload"]["call_id"] == call_id:
            payload: dict[str, Any] = item["payload"]
            return payload
    raise AssertionError(f"no DDS_CALL_STARTED for {call_id}")


# ---------------------------------------------------------------------------------------------
# The gateway's service credential
# ---------------------------------------------------------------------------------------------


async def test_every_telephony_operation_needs_the_gateway_credential(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    body = {"sip_user": SIP_USER, "dialed": "112", "sip_call_id": "x"}
    for headers in ({}, {"X-Sip-Gateway-Secret": "wrong"}, dds(tokens)):
        refused = await client.post(f"{TELEPHONY}/dial", headers=headers, json=body)
        assert refused.status_code == 401, refused.text
        assert refused.json()["code"] == "UNAUTHENTICATED"
        read = await client.get(f"{TELEPHONY}/sip-credentials/{SIP_USER}", headers=headers)
        assert read.status_code == 401
    assert await of_type(client, tokens, on_session, "DDS_CALL_STARTED") == []


async def test_an_unset_gateway_secret_refuses_everything(
    client: httpx.AsyncClient, container: Container, users: dict[str, UserId]
) -> None:
    container.settings = container.settings.model_copy(update={"sip_gateway_secret": ""})
    refused = await client.get(f"{TELEPHONY}/sip-credentials/{SIP_USER}", headers=gateway())
    assert refused.status_code == 401


# ---------------------------------------------------------------------------------------------
# dialFromSip: the dial plan through the real use case
# ---------------------------------------------------------------------------------------------


async def test_the_softphone_dials_101_and_the_call_rings_on_leg_up(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    dialed = await dial(client, "101")
    assert dialed.status_code == 201, dialed.text
    body = dialed.json()
    assert (body["session_id"], body["kind"], body["persona_id"]) == (
        str(on_session),
        "SERVICE_HEAD",
        "BRIGADE_101",
    )
    call_id = body["call_id"]
    assert body["room_name"] == f"dds-{on_session}-{call_id}"
    payload = await started_payload(client, tokens, on_session, call_id)
    assert (payload["endpoint"], payload["dialed"], payload["selection_reason"]) == (
        "SIP",
        "101",
        "OLDEST_ACTIVE",
    )
    assert payload["service_type"] == "FIRE_RESCUE"
    # `guard_dds_call_transport_ready` needs the gateway's leg too: no ring, no agent yet.
    await tick(container, on_session)
    assert (await get_call(client, tokens, on_session, call_id))["state"] == "DIALING"
    assert voice_signals.joins == []

    up = await leg(client, call_id, "UP")
    assert up.status_code == 200, up.text
    assert up.json()["state"] == "RINGING" and up.json()["available_actions"] == []
    assert voice_signals.joins[-1][2] == UUID(call_id)
    assert voice_signals.join_extras[-1]["endpoint"] == "SIP"
    assert voice_signals.join_extras[-1]["sip_user"] == SIP_USER
    joins = len(voice_signals.joins)
    again = await leg(client, call_id, "UP")  # idempotent: no second ring
    assert again.status_code == 200 and again.json()["state"] == "RINGING"
    assert len(voice_signals.joins) == joins
    assert all(extra["sip_user"] == SIP_USER for extra in voice_signals.join_extras)

    clock.advance_ms(ANSWER_AFTER_MS)
    await tick(container, on_session)
    read = await client.get(f"{TELEPHONY}/calls/{call_id}", headers=gateway())
    assert read.status_code == 200
    assert (read.json()["state"], read.json()["answered_by"]) == ("CONNECTED", "AI")

    down = await leg(client, call_id, "DOWN")
    assert down.status_code == 200
    assert (down.json()["state"], down.json()["end_reason"]) == ("ENDED", "HANGUP")
    [ended] = await of_type(client, tokens, on_session, "DDS_CALL_ENDED")
    assert ended["actor_type"] == "TRAINEE"
    assert voice_signals.cancels[-1][1:3] == (UUID(call_id), "HANGUP")
    late = await leg(client, call_id, "DOWN")  # a late BYE never fails
    assert late.status_code == 200 and late.json()["state"] == "ENDED"
    assert len(await of_type(client, tokens, on_session, "DDS_CALL_ENDED")) == 1


async def test_the_softphone_dials_a_7xxx_extension(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    by_service = await legs(client, tokens, on_session)
    assert by_service["FIRE_RESCUE"]["phone_extension"] == "101"
    extension, service = next(
        (item["phone_extension"], name)
        for name, item in by_service.items()
        if (item["phone_extension"] or "").startswith("7")
    )
    dialed = await dial(client, extension)
    assert dialed.status_code == 201, dialed.text
    payload = await started_payload(client, tokens, on_session, dialed.json()["call_id"])
    assert (payload["kind"], payload["service_type"], payload["dialed"]) == (
        "SERVICE_HEAD",
        service,
        extension,
    )


@pytest.mark.parametrize(
    ("number", "kind"),
    [
        ("112", "OPERATOR_112"),
        (CLAIMANT_DIGITS, "CLAIMANT"),
        ("8" + CLAIMANT_DIGITS[1:], "CLAIMANT"),
    ],
)
async def test_the_softphone_dials_112_and_the_claimant(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    number: str,
    kind: str,
) -> None:
    dialed = await dial(client, number)
    assert dialed.status_code == 201, dialed.text
    assert dialed.json()["kind"] == kind
    payload = await started_payload(client, tokens, on_session, dialed.json()["call_id"])
    assert (payload["endpoint"], payload["dialed"]) == ("SIP", number)


@pytest.mark.parametrize("number", ["555", "7999", "999", "104"])
async def test_an_unknown_number_is_404_dial_number_unknown(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID, number: str
) -> None:
    """`555` is nobody, `7999` is past the catalog, `999` is the gateway's echo, and `104` is a
    real service code with no leg on this card."""
    refused = await dial(client, number)
    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "DIAL_NUMBER_UNKNOWN"
    assert await of_type(client, tokens, on_session, "DDS_CALL_STARTED") == []


async def test_no_eligible_session_is_409_and_an_unknown_user_is_403(
    client: httpx.AsyncClient, tokens: dict[str, str], off_session: UUID
) -> None:
    refused = await dial(client, "112")  # trainee2 plays only an OFF session: no phone there
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "NO_ACTIVE_DDS_SESSION"
    for user in ("nobody-here", "retired1"):
        forbidden = await dial(client, "112", sip_user=user)
        assert forbidden.status_code == 403, forbidden.text


async def test_one_line_per_workstation_holds_for_the_softphone(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    assert (await dial(client, "112")).status_code == 201
    busy = await dial(client, "101")
    assert busy.status_code == 409 and busy.json()["code"] == "DDS_LINE_BUSY"


# ---------------------------------------------------------------------------------------------
# The session selection (§80.3.5)
# ---------------------------------------------------------------------------------------------


async def test_the_last_opened_card_wins_else_the_oldest(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    rubbish_version_id: ScenarioVersionId,
    clock: FakeClock,
) -> None:
    older = await started_session(
        client, tokens, users, rubbish_version_id, {"dds_brigade_call": "ON"}
    )
    clock.advance_ms(5_000)
    newer = await started_session(
        client, tokens, users, rubbish_version_id, {"dds_brigade_call": "ON"}
    )
    first = await dial(client, "112")
    assert first.status_code == 201 and first.json()["session_id"] == str(older)
    reason = (await started_payload(client, tokens, older, first.json()["call_id"]))[
        "selection_reason"
    ]
    assert reason == "OLDEST_ACTIVE"
    assert (await leg(client, first.json()["call_id"], "DOWN")).status_code == 200

    fire = (await legs(client, tokens, newer))["FIRE_RESCUE"]
    opened = await client.post(
        f"{API}/{newer}/dds/legs/{fire['assignment_id']}/open", headers=dds(tokens)
    )
    assert opened.status_code == 200, opened.text
    second = await dial(client, "112")
    assert second.status_code == 201 and second.json()["session_id"] == str(newer)
    payload = await started_payload(client, tokens, newer, second.json()["call_id"])
    assert payload["selection_reason"] == "LAST_OPENED_CARD"


def test_the_selection_rule_is_pure_and_total() -> None:
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
    a, b, c = (SessionId(UUID(int=n)) for n in (1, 2, 3))
    assert select_dds_session([]) is None
    oldest = [
        SessionCandidate(a, base + timedelta(minutes=5), None),
        SessionCandidate(b, base, None),
        SessionCandidate(c, None, None),
    ]
    assert select_dds_session(oldest) == (b, CallSelectionReason.OLDEST_ACTIVE)
    assert select_dds_session(list(reversed(oldest))) == (b, CallSelectionReason.OLDEST_ACTIVE)
    opened = [
        SessionCandidate(a, base, base + timedelta(minutes=1)),
        SessionCandidate(b, base, base + timedelta(minutes=3)),
        SessionCandidate(c, base - timedelta(hours=1), None),
    ]
    assert select_dds_session(opened) == (b, CallSelectionReason.LAST_OPENED_CARD)


# ---------------------------------------------------------------------------------------------
# reportSipLeg: FAILED, a BROWSER call, the transport not ready
# ---------------------------------------------------------------------------------------------


async def test_a_failed_leg_is_a_system_abort(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    voice_signals: InMemoryVoiceSignals,
) -> None:
    call_id = (await dial(client, "112")).json()["call_id"]
    failed = await leg(client, call_id, "FAILED", sip_status=486)
    assert failed.status_code == 200, failed.text
    assert (failed.json()["state"], failed.json()["end_reason"]) == ("ENDED", "ABORT")
    [ended] = await of_type(client, tokens, on_session, "DDS_CALL_ENDED")
    assert (ended["actor_type"], ended["payload"]["reason"]) == ("SYSTEM", "ABORT")
    assert voice_signals.cancels[-1][1:3] == (UUID(call_id), "ABORT")


async def test_a_browser_call_has_no_leg_and_an_unknown_call_is_404(
    client: httpx.AsyncClient, tokens: dict[str, str], on_session: UUID
) -> None:
    started = await start_claimant_call(client, tokens, on_session)
    call = started.json()["call"]
    assert call["endpoint"] == "BROWSER"
    refused = await leg(client, call["call_id"], "UP")
    assert refused.status_code == 409 and refused.json()["code"] == "INVALID_TRANSITION"
    missing = await leg(client, "00000000-0000-4000-8000-000000000000", "UP")
    assert missing.status_code == 404
    unread = await client.get(
        f"{TELEPHONY}/calls/00000000-0000-4000-8000-000000000000", headers=gateway()
    )
    assert unread.status_code == 404


async def test_leg_up_waits_for_the_transport(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    transport: FakeCallTransportStatus,
) -> None:
    call_id = (await dial(client, "112")).json()["call_id"]
    transport.ready = False
    assert (await leg(client, call_id, "UP")).json()["state"] == "DIALING"
    transport.ready = True
    assert (await leg(client, call_id, "UP")).json()["state"] == "RINGING"


# ---------------------------------------------------------------------------------------------
# The endpoint choice (§80.3.7): a live binding wins; its loss ⇒ the browser
# ---------------------------------------------------------------------------------------------


async def test_a_live_binding_makes_the_button_call_sip_and_its_loss_the_browser(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
    sip_bindings: InMemorySipBindings,
) -> None:
    await sip_bindings.bind(SIP_USER, contact="sip:trainee2@127.0.0.1:5070", expires_at=0, ttl_s=60)
    started = await start_claimant_call(client, tokens, on_session)
    assert started.status_code == 201, started.text
    call = started.json()["call"]
    assert (call["endpoint"], call["state"], started.json()["voice"]) == ("SIP", "DIALING", None)
    # The gateway is told at once, and again while it has not rung the softphone.
    assert voice_signals.join_extras[-1]["sip_user"] == SIP_USER
    assert voice_signals.join_extras[-1]["endpoint"] == "SIP"
    published = len(voice_signals.joins)
    clock.advance_ms(3_000)
    await tick(container, on_session)
    assert len(voice_signals.joins) == published + 1
    assert (await get_call(client, tokens, on_session, call["call_id"]))["state"] == "DIALING"
    assert (await leg(client, call["call_id"], "UP")).json()["state"] == "RINGING"
    assert (await leg(client, call["call_id"], "DOWN")).json()["end_reason"] == "HANGUP"

    await sip_bindings.unbind(SIP_USER)  # a Redis flush, an expired key, the softphone off
    again = await start_claimant_call(client, tokens, on_session)
    assert again.status_code == 201, again.text
    assert again.json()["call"]["endpoint"] == "BROWSER"
    assert again.json()["voice"] is not None
    assert "sip_user" not in voice_signals.join_extras[-1]


async def test_a_binding_counts_only_when_the_deployment_offers_sip(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    on_session: UUID,
    container: Container,
    sip_bindings: InMemorySipBindings,
) -> None:
    container.settings = container.settings.model_copy(update={"telephony_endpoints": "browser"})
    await sip_bindings.bind(SIP_USER, contact="sip:x@127.0.0.1", expires_at=0, ttl_s=60)
    started = await start_claimant_call(client, tokens, on_session)
    assert started.json()["call"]["endpoint"] == "BROWSER"


async def test_a_call_in_rings_the_softphone_and_leg_up_is_the_trainee_s_answer(
    client: httpx.AsyncClient,
    tokens: dict[str, str],
    users: dict[str, UserId],
    call_in_version_id: ScenarioVersionId,
    container: Container,
    clock: FakeClock,
    voice_signals: InMemoryVoiceSignals,
    sip_bindings: InMemorySipBindings,
) -> None:
    await sip_bindings.bind(SIP_USER, contact="sip:trainee2@127.0.0.1", expires_at=0, ttl_s=60)
    session_id = await started_session(client, tokens, users, call_in_version_id)
    clock.advance_ms(15_500)
    await tick(container, session_id)
    [started] = await of_type(client, tokens, session_id, "DDS_CALL_STARTED")
    call_id = started["payload"]["call_id"]
    assert started["payload"]["endpoint"] == "SIP"
    assert (await get_call(client, tokens, session_id, call_id))["state"] == "RINGING"
    assert voice_signals.join_extras[-1]["sip_user"] == SIP_USER
    assert voice_signals.join_extras[-1]["direction"] == "INBOUND"
    up = await leg(client, call_id, "UP")
    assert (up.json()["state"], up.json()["answered_by"]) == ("CONNECTED", "TRAINEE")
    [answered] = await of_type(client, tokens, session_id, "DDS_CALL_ANSWERED")
    assert (answered["actor_type"], answered["payload"]["answered_by"]) == ("TRAINEE", "TRAINEE")


# ---------------------------------------------------------------------------------------------
# getSipCredential (migration 0015)
# ---------------------------------------------------------------------------------------------


async def test_the_sip_credential_is_403_unknown_404_unset_200_set(
    client: httpx.AsyncClient, container: Container, users: dict[str, UserId]
) -> None:
    unknown = await client.get(f"{TELEPHONY}/sip-credentials/nobody-here", headers=gateway())
    assert unknown.status_code == 403
    retired = await client.get(f"{TELEPHONY}/sip-credentials/retired1", headers=gateway())
    assert retired.status_code == 403
    unset = await client.get(f"{TELEPHONY}/sip-credentials/{SIP_USER}", headers=gateway())
    assert unset.status_code == 404 and unset.json()["code"] == "NOT_FOUND"
    digest = sip_ha1(SIP_USER, "sim112-test", "test-fixture-user-sip-password")
    async with container.unit_of_work() as uow:
        assert await uow.users.set_sip_ha1(SIP_USER, digest)
        await uow.commit()
    try:
        found = await client.get(f"{TELEPHONY}/sip-credentials/{SIP_USER}", headers=gateway())
        assert found.status_code == 200
        assert found.json() == {"username": SIP_USER, "realm": "sim112-test", "ha1": digest}
    finally:
        async with container.unit_of_work() as uow:
            await uow.users.set_sip_ha1(SIP_USER, None)
            await uow.commit()


async def test_the_database_refuses_a_malformed_ha1(
    container: Container, users: dict[str, UserId]
) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with container.unit_of_work() as uow:
            await uow.users.set_sip_ha1(SIP_USER, "NOT-A-DIGEST")
            await uow.commit()
