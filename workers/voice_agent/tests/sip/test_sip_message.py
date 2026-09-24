"""`message.py`: parsing, serialisation, Digest, SDP offer/answer, TCP framing (HLD 80 §80.2.1)."""

from __future__ import annotations

import pytest
from voice_agent.transport.sip.message import (
    PT_PCMA,
    PT_PCMU,
    SipParseError,
    StreamFramer,
    build_authorization,
    build_response,
    build_sdp,
    choose_codec,
    digest_ha1,
    digest_response,
    parse_auth_header,
    parse_message,
    parse_name_addr,
    parse_sdp,
    parse_uri,
    parse_via,
)

INVITE = (
    b"INVITE sip:999@sim112 SIP/2.0\r\n"
    b"Via: SIP/2.0/UDP 10.0.0.5:5062;branch=z9hG4bKabc;rport\r\n"
    b"v: SIP/2.0/UDP 10.0.0.1;branch=z9hG4bKproxy\r\n"
    b"Max-Forwards: 70\r\n"
    b'f: "Trainee" <sip:trainee@sim112>;tag=aa11\r\n'
    b"t: <sip:999@sim112>\r\n"
    b"i: call-1@10.0.0.5\r\n"
    b"CSeq: 1 INVITE\r\n"
    b"m: <sip:trainee@10.0.0.5:5062>\r\n"
    b"c: application/sdp\r\n"
    b"Subject: folded\r\n"
    b" header value\r\n"
    b"l: 4\r\n"
    b"\r\n"
    b"abcdEXTRA"
)


def test_a_request_parses_with_compact_headers_folding_and_content_length() -> None:
    message = parse_message(INVITE)
    assert message.is_request and message.method == "INVITE" and message.uri == "sip:999@sim112"
    assert message.call_id == "call-1@10.0.0.5"
    assert message.cseq == (1, "INVITE")
    assert len(message.get_all("Via")) == 2
    assert message.get("Subject") == "folded header value"
    assert message.body == b"abcd"  # Content-Length wins over trailing bytes
    via = message.top_via
    assert via is not None and via.branch == "z9hG4bKabc" and via.port == 5062
    assert "rport" in via.params


def test_serialisation_round_trips_and_writes_a_truthful_content_length() -> None:
    message = parse_message(INVITE)
    message.body = b"0123456789"
    again = parse_message(message.to_bytes())
    assert again.body == b"0123456789"
    assert again.get("Content-Length") == "10"
    assert again.get_all("Via") == message.get_all("Via")


def test_a_response_copies_via_from_to_call_id_cseq_and_adds_the_to_tag() -> None:
    request = parse_message(INVITE)
    response = build_response(request, 180, to_tag="bb22")
    assert response.status == 180 and response.reason == "Ringing"
    assert response.get_all("Via") == request.get_all("Via")
    assert parse_name_addr(response.get("To") or "").tag == "bb22"
    parsed = parse_message(response.to_bytes())
    assert parsed.status == 180 and parsed.cseq == (1, "INVITE")


@pytest.mark.parametrize(
    ("raw", "has_partial"),
    [
        (b"", False),
        (b"\x00\xff\xfe garbage", False),
        (b"HELLO WORLD\r\n\r\n", False),
        (b"INVITE sip:1@x SIP/3.0\r\n\r\n", False),
        (b"SIP/2.0 99 Too Low\r\n\r\n", False),
        (b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP h;branch=z9hG4bK1\r\n\r\n", True),
        (b"OPTIONS sip:x SIP/2.0\r\nno colon here\r\n\r\n", True),
        (
            b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP h;branch=z9hG4bK1\r\nFrom: <sip:a@h>\r\n"
            b"To: <sip:b@h>\r\nCall-ID: c\r\nCSeq: x OPTIONS\r\n\r\n",
            True,
        ),
        (
            b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP h;branch=z9hG4bK1\r\nFrom: <sip:a@h>\r\n"
            b"To: <sip:b@h>\r\nCall-ID: c\r\nCSeq: 1 INVITE\r\n\r\n",
            True,
        ),
        (
            b"OPTIONS sip:x SIP/2.0\r\nVia: SIP/2.0/UDP h;branch=z9hG4bK1\r\nFrom: <sip:a@h>\r\n"
            b"To: <sip:b@h>\r\nCall-ID: c\r\nCSeq: 1 OPTIONS\r\nContent-Length: 50\r\n\r\nshort",
            True,
        ),
    ],
)
def test_malformed_messages_raise_a_parse_error_carrying_what_did_parse(
    raw: bytes, has_partial: bool
) -> None:
    with pytest.raises(SipParseError) as excinfo:
        parse_message(raw)
    assert (excinfo.value.partial is not None) is has_partial


def test_via_uri_and_name_addr_shapes() -> None:
    via = parse_via("SIP/2.0/TCP [::1]:5070;branch=z9hG4bKx;received=1.2.3.4")
    assert via.transport == "TCP" and via.host == "::1" and via.port == 5070
    assert via.params["received"] == "1.2.3.4"
    uri = parse_uri("sip:101@192.168.1.10:5060;transport=udp")
    assert (uri.user, uri.host, uri.port, uri.params) == (
        "101",
        "192.168.1.10",
        5060,
        {"transport": "udp"},
    )
    addr = parse_name_addr("sip:trainee@sim112;tag=zz")
    assert addr.uri == "sip:trainee@sim112" and addr.tag == "zz"
    with pytest.raises(ValueError):
        parse_uri("http://example.org")
    with pytest.raises(ValueError):
        parse_via("SIP/2.0/UDP host:99999")


def test_digest_with_qop_auth_matches_rfc_2617_and_the_ua_side_agrees() -> None:
    # RFC 2617 §3.5's worked example (HTTP, but the arithmetic is the same).
    ha1 = digest_ha1("Mufasa", "testrealm@host.com", "Circle Of Life")
    response = digest_response(
        ha1,
        method="GET",
        uri="/dir/index.html",
        nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093",
        qop="auth",
        nc="00000001",
        cnonce="0a4f113b",
    )
    assert response == "6629fae49393a05397450978507c4ef1"
    challenge = {"realm": "r", "nonce": "n1", "qop": "auth"}
    header = build_authorization(
        username="u", password="p", method="REGISTER", uri="sip:r", challenge=challenge
    )
    scheme, params = parse_auth_header(header)
    assert scheme == "Digest" and params["qop"] == "auth"
    expected = digest_response(
        digest_ha1("u", "r", "p"),
        method="REGISTER",
        uri="sip:r",
        nonce="n1",
        qop="auth",
        nc=params["nc"],
        cnonce=params["cnonce"],
    )
    assert params["response"] == expected


OFFER = (
    b"v=0\r\no=- 1 1 IN IP4 10.0.0.5\r\ns=-\r\nc=IN IP4 10.0.0.5\r\nt=0 0\r\n"
    b"m=audio 40000 RTP/AVP 9 0 8 101\r\na=rtpmap:9 G722/8000\r\na=rtpmap:0 PCMU/8000\r\n"
    b"a=rtpmap:8 PCMA/8000\r\na=rtpmap:101 telephone-event/8000\r\na=ptime:20\r\n"
    b"m=video 40002 RTP/AVP 96\r\nc=IN IP4 10.9.9.9\r\n"
)


def test_sdp_offer_parses_the_first_audio_line_and_the_answer_prefers_pcma() -> None:
    offer = parse_sdp(OFFER)
    assert offer.address == "10.0.0.5" and offer.port == 40000
    assert offer.payload_types == (9, 0, 8, 101) and offer.ptime == 20
    assert choose_codec(offer) == PT_PCMA


def test_the_answer_accepts_pcmu_and_refuses_an_offer_without_g711() -> None:
    pcmu_only = parse_sdp(
        build_sdp(address="1.2.3.4", port=4000, payload_types=(PT_PCMU,), session_id=1)
    )
    assert choose_codec(pcmu_only) == PT_PCMU
    g722_only = parse_sdp(
        b"v=0\r\nc=IN IP4 1.2.3.4\r\nm=audio 4000 RTP/AVP 9\r\na=rtpmap:9 G722/8000\r\n"
    )
    assert choose_codec(g722_only) is None
    with pytest.raises(ValueError):
        parse_sdp(b"v=0\r\nm=video 1 RTP/AVP 96\r\n")


def test_the_tcp_framer_splits_a_stream_by_content_length() -> None:
    first = build_response(parse_message(INVITE), 200, body=b"hello").to_bytes()
    second = build_response(parse_message(INVITE), 100).to_bytes()
    framer = StreamFramer()
    stream = b"\r\n\r\n" + first + second
    frames = []
    for i in range(0, len(stream), 7):  # dribbled in 7-byte chunks
        frames.extend(framer.feed(stream[i : i + 7]))
    assert frames == [first, second]
    assert parse_message(frames[0]).body == b"hello"
