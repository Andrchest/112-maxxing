"""SDES negotiation and the SRTP context (I7 E44; RFC 4568, RFC 3711; `transport/sip/srtp.py`).

Pure unit tests: crypto-line parsing, the answerer's decision per signalling transport (SRTP
required over TLS, plain RTP over UDP/TCP), the offerer's check of an answer, and one packet
protected and unprotected through libsrtp. No socket.
"""

from __future__ import annotations

import base64

import pylibsrtp
import pytest
from voice_agent.transport.sip.message import PT_PCMA, build_sdp, parse_sdp
from voice_agent.transport.sip.rtp import RtpPacket
from voice_agent.transport.sip.srtp import (
    MASTER_KEY_BYTES,
    PROTO_AVP,
    PROTO_SAVP,
    SRTP_SUITE,
    CryptoAttribute,
    MediaRejected,
    SrtpContext,
    SrtpError,
    accept_answer,
    negotiate_answer,
    new_crypto,
    parse_crypto,
)

#: TEST FIXTURE ONLY — a fixed, public SRTP master key + salt (RFC 4568 §9.1's example line).
RFC_4568_EXAMPLE = (
    "1 AES_CM_128_HMAC_SHA1_80 inline:PS1uQCVeeCFCanVmcjkpPywjNWhcYD0mXXtxaVBR|2^20|1:4"
)
KEY_A = bytes(range(MASTER_KEY_BYTES))
KEY_B = bytes(range(100, 100 + MASTER_KEY_BYTES))


def _line(key: bytes, tag: int = 1, suite: str = SRTP_SUITE, extra: str = "") -> str:
    return f"{tag} {suite} inline:{base64.b64encode(key).decode()}{extra}"


def _offer(protocol: str, *crypto: str) -> bytes:
    return build_sdp(
        address="127.0.0.1",
        port=40000,
        payload_types=(PT_PCMA,),
        session_id=1,
        protocol=protocol,
        crypto=crypto,
    )


# -- key parsing ----------------------------------------------------------------------------------


def test_a_crypto_line_parses_to_its_tag_suite_and_30_byte_key_and_round_trips() -> None:
    parsed = parse_crypto(_line(KEY_A, tag=7))
    assert (parsed.tag, parsed.suite, parsed.key) == (7, SRTP_SUITE, KEY_A)
    assert parse_crypto(parsed.sdp_value()) == parsed
    with_lifetime = parse_crypto(_line(KEY_A, extra="|2^31"))
    assert with_lifetime.key == KEY_A
    assert parse_crypto(_line(KEY_A) + " WSH=64").key == KEY_A  # a window hint is harmless


@pytest.mark.parametrize(
    ("value", "why"),
    [
        (_line(KEY_A, suite="AES_CM_128_HMAC_SHA1_32"), "suite"),
        (_line(KEY_A, suite="F8_128_HMAC_SHA1_80"), "suite"),
        (RFC_4568_EXAMPLE, "MKI"),
        (_line(KEY_A[:16]), "bytes"),
        ("1 AES_CM_128_HMAC_SHA1_80 inline:not*base64*at*all", "base64"),
        ("1 AES_CM_128_HMAC_SHA1_80 uri:https://example.invalid/key", "inline"),
        (_line(KEY_A) + ";" + _line(KEY_B).split()[2], "more than one"),
        (_line(KEY_A) + " UNENCRYPTED_SRTP", "session parameter"),
        (_line(KEY_A) + " KDR=1", "session parameter"),
        ("x AES_CM_128_HMAC_SHA1_80 inline:" + base64.b64encode(KEY_A).decode(), "tag"),
        ("1 AES_CM_128_HMAC_SHA1_80", "tag, a suite"),
    ],
)
def test_an_unsupported_or_malformed_crypto_line_is_refused(value: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        parse_crypto(value)


def test_sdp_carries_the_protocol_and_crypto_lines_and_never_prints_a_key() -> None:
    media = parse_sdp(_offer(PROTO_SAVP, _line(KEY_A), _line(KEY_B, tag=2)))
    assert media.protocol == PROTO_SAVP
    assert media.crypto == (_line(KEY_A), _line(KEY_B, tag=2))
    assert base64.b64encode(KEY_A).decode() not in repr(media)
    assert "redacted" in repr(parse_crypto(_line(KEY_A)))
    assert parse_sdp(_offer(PROTO_AVP)).protocol == PROTO_AVP


def test_new_crypto_is_a_fresh_random_key_per_call() -> None:
    first, second = new_crypto(), new_crypto(3)
    assert len(first.key) == MASTER_KEY_BYTES and first.key != second.key
    assert (second.tag, second.suite) == (3, SRTP_SUITE)


# -- the answerer's decision ----------------------------------------------------------------------


def test_over_tls_an_savp_offer_with_a_good_crypto_line_is_answered_with_srtp() -> None:
    offer = parse_sdp(_offer(PROTO_SAVP, _line(KEY_A, tag=5)))
    answer = negotiate_answer(offer, secure_signalling=True)
    assert answer is not None
    assert answer.remote.key == KEY_A and answer.remote.tag == 5
    assert answer.local.tag == 5 and answer.local.suite == SRTP_SUITE
    assert answer.local.key != KEY_A  # our own key, not an echo of theirs


def test_over_tls_the_first_acceptable_line_wins_after_unsupported_ones() -> None:
    offer = parse_sdp(
        _offer(
            PROTO_SAVP,
            _line(KEY_B, tag=1, suite="AES_256_CM_HMAC_SHA1_80"),
            _line(KEY_B, tag=2, extra="|2^20|1:4"),
            _line(KEY_A, tag=3),
        )
    )
    answer = negotiate_answer(offer, secure_signalling=True)
    assert answer is not None and answer.remote.tag == 3 and answer.remote.key == KEY_A


@pytest.mark.parametrize(
    "body",
    [
        _offer(PROTO_AVP),  # plain RTP over TLS
        _offer(PROTO_AVP, _line(KEY_A)),  # "best effort" crypto on RTP/AVP: still refused
        _offer(PROTO_SAVP),  # SAVP with no key at all
        _offer(PROTO_SAVP, _line(KEY_A, suite="AES_CM_128_HMAC_SHA1_32")),  # no suite we speak
    ],
)
def test_over_tls_an_offer_without_usable_srtp_is_rejected_488(body: bytes) -> None:
    with pytest.raises(MediaRejected):
        negotiate_answer(parse_sdp(body), secure_signalling=True)


def test_over_plain_sip_rtp_stays_rtp_and_an_savp_offer_is_rejected() -> None:
    assert negotiate_answer(parse_sdp(_offer(PROTO_AVP)), secure_signalling=False) is None
    # A key offered in clear SIP protects nothing: ignored, plain RTP.
    assert (
        negotiate_answer(parse_sdp(_offer(PROTO_AVP, _line(KEY_A))), secure_signalling=False)
        is None
    )
    with pytest.raises(MediaRejected, match="TLS"):
        negotiate_answer(parse_sdp(_offer(PROTO_SAVP, _line(KEY_A))), secure_signalling=False)


# -- the offerer's check of an answer -------------------------------------------------------------


def test_the_offerer_accepts_only_an_savp_answer_under_its_own_tag() -> None:
    local = CryptoAttribute(tag=1, suite=SRTP_SUITE, key=KEY_A)
    good = parse_sdp(_offer(PROTO_SAVP, _line(KEY_B, tag=1)))
    assert accept_answer(good, local).key == KEY_B
    for bad in (
        _offer(PROTO_AVP, _line(KEY_B, tag=1)),
        _offer(PROTO_SAVP, _line(KEY_B, tag=2)),
        _offer(PROTO_SAVP),
    ):
        with pytest.raises(MediaRejected):
            accept_answer(parse_sdp(bad), local)


# -- the SRTP context over libsrtp ----------------------------------------------------------------


def _packet(seq: int, payload: bytes) -> bytes:
    return RtpPacket(PT_PCMA, seq, seq * 160, 0x1234ABCD, payload).to_bytes()


def test_a_packet_is_encrypted_on_the_wire_and_the_far_end_decrypts_it() -> None:
    payload = bytes(range(160))
    plain = _packet(1, payload)
    ours = SrtpContext(local_key=KEY_A, remote_key=KEY_B)
    theirs = SrtpContext(local_key=KEY_B, remote_key=KEY_A)
    wire = ours.protect(plain)
    assert len(wire) == len(plain) + 10  # the 80-bit authentication tag
    assert wire[:12] == plain[:12]  # the RTP header travels in clear (RFC 3711 §3.1)
    assert wire[12 : 12 + len(payload)] != payload
    assert theirs.unprotect(wire) == plain
    # And an independent libsrtp session keyed from the same line agrees (no wrapper magic).
    policy = pylibsrtp.Policy(key=KEY_A, ssrc_type=pylibsrtp.Policy.SSRC_ANY_INBOUND)
    assert pylibsrtp.Session(policy).unprotect(ours.protect(_packet(2, payload))) == _packet(
        2, payload
    )


def test_a_tampered_replayed_or_wrongly_keyed_packet_is_refused() -> None:
    ours = SrtpContext(local_key=KEY_A, remote_key=KEY_B)
    theirs = SrtpContext(local_key=KEY_B, remote_key=KEY_A)
    wire = ours.protect(_packet(10, b"\x55" * 160))
    tampered = wire[:20] + bytes([wire[20] ^ 1]) + wire[21:]
    with pytest.raises(SrtpError):
        theirs.unprotect(tampered)
    assert theirs.unprotect(wire)
    with pytest.raises(SrtpError):
        theirs.unprotect(wire)  # a replay
    stranger = SrtpContext(local_key=KEY_B, remote_key=KEY_B)
    with pytest.raises(SrtpError):
        stranger.unprotect(ours.protect(_packet(11, b"\x55" * 160)))
    assert theirs.failures == 2


def test_rekey_inbound_switches_to_the_new_far_key_only_when_it_changed() -> None:
    receiver = SrtpContext(local_key=KEY_B, remote_key=KEY_A)
    assert receiver.rekey_inbound(KEY_A) is False
    new_key = bytes(reversed(KEY_A))
    assert receiver.rekey_inbound(new_key) is True
    sender = SrtpContext(local_key=new_key, remote_key=KEY_B)
    assert receiver.unprotect(sender.protect(_packet(1, b"\x01" * 160))) == _packet(
        1, b"\x01" * 160
    )
