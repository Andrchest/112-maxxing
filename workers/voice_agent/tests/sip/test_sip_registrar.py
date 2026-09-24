"""`registrar.py`: 401 → 200, wrong password 403, expiry, unbind, stale nonce (80 §80.2.1)."""

from __future__ import annotations

from sip_testkit import TEST_REALM, TEST_SIP_PASSWORD, FakeClock
from voice_agent.transport.sip.message import (
    SipMessage,
    build_authorization,
    parse_auth_header,
)
from voice_agent.transport.sip.registrar import NONCE_TTL_S, Registrar

SOURCE = ("10.0.0.5", 5062)


def _register(
    *, user: str = "trainee", expires: int | None = 300, contact: str | None = None
) -> SipMessage:
    request = SipMessage(method="REGISTER", uri=f"sip:{TEST_REALM}")
    request.add("Via", "SIP/2.0/UDP 10.0.0.5:5062;branch=z9hG4bKreg1;rport")
    request.add("From", f"<sip:{user}@{TEST_REALM}>;tag=f1")
    request.add("To", f"<sip:{user}@{TEST_REALM}>")
    request.add("Call-ID", "reg-1")
    request.add("CSeq", "1 REGISTER")
    request.add("Contact", contact or f"<sip:{user}@10.0.0.5:5062>")
    if expires is not None:
        request.add("Expires", str(expires))
    return request


def _authorised(request: SipMessage, challenge: SipMessage, *, password: str) -> SipMessage:
    _, params = parse_auth_header(challenge.get("WWW-Authenticate") or "")
    username = (request.get("From") or "").split("sip:")[1].split("@")[0]
    request.add(
        "Authorization",
        build_authorization(
            username=username,
            password=password,
            method="REGISTER",
            uri=request.uri or "",
            challenge=params,
        ),
    )
    return request


def _registrar(clock: FakeClock) -> Registrar:
    return Registrar(realm=TEST_REALM, password=TEST_SIP_PASSWORD, now=clock)


async def test_register_is_challenged_then_bound_with_the_right_password() -> None:
    clock = FakeClock()
    registrar = _registrar(clock)
    challenge = await registrar.handle_register(_register(), source=SOURCE, transport="UDP")
    assert challenge.status == 401
    header = challenge.get("WWW-Authenticate") or ""
    assert header.startswith("Digest ") and f'realm="{TEST_REALM}"' in header
    assert 'qop="auth"' in header
    ok = await registrar.handle_register(
        _authorised(_register(), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    assert ok.status == 200
    assert ok.get("Expires") == "300"
    binding = registrar.lookup("trainee")
    assert binding is not None and binding.contact == "sip:trainee@10.0.0.5:5062"
    assert binding.source == SOURCE and binding.transport == "UDP"


async def test_a_wrong_password_is_403_and_binds_nothing() -> None:
    registrar = _registrar(FakeClock())
    challenge = await registrar.handle_register(_register(), source=SOURCE, transport="UDP")
    refused = await registrar.handle_register(
        _authorised(_register(), challenge, password="wrong-test-password"),
        source=SOURCE,
        transport="UDP",
    )
    assert refused.status == 403
    assert registrar.lookup("trainee") is None


async def test_a_binding_expires_and_expires_zero_unbinds() -> None:
    clock = FakeClock()
    registrar = _registrar(clock)
    challenge = await registrar.handle_register(
        _register(expires=60), source=SOURCE, transport="UDP"
    )
    await registrar.handle_register(
        _authorised(_register(expires=60), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    clock.advance(59)
    assert registrar.is_registered("trainee")
    clock.advance(2)
    assert not registrar.is_registered("trainee")
    assert registrar.bindings() == []

    challenge = await registrar.handle_register(_register(), source=SOURCE, transport="UDP")
    await registrar.handle_register(
        _authorised(_register(), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    assert registrar.is_registered("trainee")
    challenge = await registrar.handle_register(
        _register(expires=0), source=SOURCE, transport="UDP"
    )
    unbound = await registrar.handle_register(
        _authorised(_register(expires=0), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    assert unbound.status == 200
    assert not registrar.is_registered("trainee")


async def test_expires_is_capped_and_a_contact_expires_param_wins() -> None:
    clock = FakeClock()
    registrar = _registrar(clock)
    request = _register(expires=99_999, contact="<sip:trainee@10.0.0.5:5062>;expires=120")
    challenge = await registrar.handle_register(request, source=SOURCE, transport="UDP")
    request = _register(expires=99_999, contact="<sip:trainee@10.0.0.5:5062>;expires=120")
    ok = await registrar.handle_register(
        _authorised(request, challenge, password=TEST_SIP_PASSWORD), source=SOURCE, transport="UDP"
    )
    assert ok.get("Expires") == "120"
    request = _register(expires=99_999)
    challenge = await registrar.handle_register(request, source=SOURCE, transport="UDP")
    ok = await registrar.handle_register(
        _authorised(_register(expires=99_999), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    assert ok.get("Expires") == "3600"


async def test_a_stale_or_unknown_nonce_is_challenged_again_not_refused() -> None:
    clock = FakeClock()
    registrar = _registrar(clock)
    challenge = await registrar.handle_register(_register(), source=SOURCE, transport="UDP")
    clock.advance(NONCE_TTL_S + 1)
    stale = await registrar.handle_register(
        _authorised(_register(), challenge, password=TEST_SIP_PASSWORD),
        source=SOURCE,
        transport="UDP",
    )
    assert stale.status == 401 and "stale=true" in (stale.get("WWW-Authenticate") or "")
    forged = _register()
    forged.add("Authorization", 'Digest username="trainee", nonce="made-up", response="00"')
    assert (await registrar.handle_register(forged, source=SOURCE, transport="UDP")).status == 401


async def test_a_user_cannot_bind_someone_elses_address_of_record() -> None:
    registrar = _registrar(FakeClock())
    challenge = await registrar.handle_register(
        _register(user="alice"), source=SOURCE, transport="UDP"
    )
    _, params = parse_auth_header(challenge.get("WWW-Authenticate") or "")
    request = _register(user="alice")
    request.add(
        "Authorization",
        build_authorization(
            username="mallory",
            password=TEST_SIP_PASSWORD,
            method="REGISTER",
            uri=request.uri or "",
            challenge=params,
        ),
    )
    assert (await registrar.handle_register(request, source=SOURCE, transport="UDP")).status == 403
