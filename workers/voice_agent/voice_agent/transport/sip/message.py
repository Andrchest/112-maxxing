"""The RFC 3261 subset the gateway speaks (HLD 80 §80.2.1 `message.py`, D22).

Parse and serialise requests and responses; the header shapes a registrar and a UAS need (`Via`
with `rport`/`branch`/`received`, `From`/`To` tags, `CSeq`, `Contact`, `Expires`,
`Content-Length`); Digest challenge/response (MD5, `qop=auth`, RFC 2617 §3.2.2); SDP offer/answer
over the first audio m-line only (RFC 3264); and the Content-Length framing a TCP stream needs.

Nothing here does I/O. A message that does not parse raises `SipParseError`, which carries the
part that *did* parse, so the listener can still answer `400 Bad Request` to a broken request
whose `Via` survived (§80.2.1: "a malformed message is answered `400` and never raises out of the
listener").
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass, field

__all__ = [
    "PT_PCMA",
    "PT_PCMU",
    "REASON_PHRASES",
    "NameAddr",
    "SdpMedia",
    "SipMessage",
    "SipParseError",
    "SipUri",
    "StreamFramer",
    "Via",
    "build_authorization",
    "build_challenge",
    "build_response",
    "build_sdp",
    "choose_codec",
    "digest_ha1",
    "digest_response",
    "new_branch",
    "new_call_id",
    "new_tag",
    "parse_auth_header",
    "parse_cseq",
    "parse_message",
    "parse_name_addr",
    "parse_sdp",
    "parse_uri",
    "parse_via",
    "user_of",
]

SIP_VERSION = "SIP/2.0"
#: RFC 3261 §8.1.1.7: every branch this stack mints starts with the magic cookie.
BRANCH_COOKIE = "z9hG4bK"
#: A datagram or a TCP head beyond this is refused rather than buffered (no allocation attack).
MAX_HEAD_BYTES = 64 * 1024
MAX_BODY_BYTES = 64 * 1024

PT_PCMU = 0
PT_PCMA = 8
STATIC_RTPMAP = {PT_PCMU: "PCMU/8000", PT_PCMA: "PCMA/8000"}

REASON_PHRASES = {
    100: "Trying",
    180: "Ringing",
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    480: "Temporarily Unavailable",
    481: "Call/Transaction Does Not Exist",
    486: "Busy Here",
    487: "Request Terminated",
    488: "Not Acceptable Here",
    500: "Server Internal Error",
    501: "Not Implemented",
    503: "Service Unavailable",
}

#: RFC 3261 §7.3.3 compact forms.
_COMPACT = {
    "v": "Via",
    "f": "From",
    "t": "To",
    "i": "Call-ID",
    "m": "Contact",
    "l": "Content-Length",
    "c": "Content-Type",
    "k": "Supported",
    "s": "Subject",
    "e": "Content-Encoding",
}
_CANONICAL = {
    name.lower(): name
    for name in (
        "Via",
        "From",
        "To",
        "Call-ID",
        "CSeq",
        "Contact",
        "Content-Length",
        "Content-Type",
        "Max-Forwards",
        "Expires",
        "WWW-Authenticate",
        "Authorization",
        "Proxy-Authenticate",
        "Proxy-Authorization",
        "User-Agent",
        "Server",
        "Allow",
        "Accept",
        "Supported",
        "Record-Route",
        "Route",
    )
}
_TOKEN = re.compile(r"^[A-Za-z0-9\-.!%*_+`'~]+$")
_REQUIRED_REQUEST_HEADERS = ("Via", "From", "To", "Call-ID", "CSeq")


class SipParseError(ValueError):
    """The bytes are not a SIP message this stack accepts. `partial` is what parsed before it."""

    def __init__(self, message: str, partial: SipMessage | None = None) -> None:
        super().__init__(message)
        self.partial = partial


def _canonical(name: str) -> str:
    stripped = name.strip()
    lowered = stripped.lower()
    if lowered in _COMPACT:
        return _COMPACT[lowered]
    return _CANONICAL.get(lowered, stripped)


def _split_commas(value: str) -> list[str]:
    """Split a header value on commas that are outside quotes and angle brackets."""
    parts: list[str] = []
    depth_angle = 0
    quoted = False
    current: list[str] = []
    for char in value:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "<":
            depth_angle += 1
        elif not quoted and char == ">":
            depth_angle = max(0, depth_angle - 1)
        if char == "," and not quoted and depth_angle == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


@dataclass
class SipMessage:
    """One request (`method` + `uri`) or response (`status` + `reason`)."""

    method: str | None = None
    uri: str | None = None
    status: int | None = None
    reason: str = ""
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""

    @property
    def is_request(self) -> bool:
        return self.method is not None

    def get(self, name: str) -> str | None:
        wanted = _canonical(name)
        for key, value in self.headers:
            if key == wanted:
                return value
        return None

    def get_all(self, name: str) -> list[str]:
        wanted = _canonical(name)
        return [value for key, value in self.headers if key == wanted]

    def add(self, name: str, value: str) -> None:
        self.headers.append((_canonical(name), value))

    def set(self, name: str, value: str) -> None:
        """Replace every occurrence of `name` by one value, keeping the first one's position."""
        wanted = _canonical(name)
        replaced = False
        kept: list[tuple[str, str]] = []
        for key, existing in self.headers:
            if key == wanted:
                if not replaced:
                    kept.append((key, value))
                    replaced = True
                continue
            kept.append((key, existing))
        if not replaced:
            kept.append((wanted, value))
        self.headers = kept

    def remove(self, name: str) -> None:
        wanted = _canonical(name)
        self.headers = [(key, value) for key, value in self.headers if key != wanted]

    @property
    def call_id(self) -> str:
        return self.get("Call-ID") or ""

    @property
    def cseq(self) -> tuple[int, str]:
        return parse_cseq(self.get("CSeq") or "")

    @property
    def top_via(self) -> Via | None:
        vias = self.get_all("Via")
        return parse_via(vias[0]) if vias else None

    def to_bytes(self) -> bytes:
        """Serialise with a truthful `Content-Length` (always written, RFC 3261 §20.14)."""
        if self.is_request:
            start = f"{self.method} {self.uri} {SIP_VERSION}"
        else:
            reason = self.reason or REASON_PHRASES.get(self.status or 0, "")
            start = f"{SIP_VERSION} {self.status} {reason}"
        lines = [start]
        lines.extend(f"{key}: {value}" for key, value in self.headers if key != "Content-Length")
        lines.append(f"Content-Length: {len(self.body)}")
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + self.body

    def summary(self) -> str:
        """One log line: never a header value that could carry a credential."""
        if self.is_request:
            return f"{self.method} {self.uri} call-id={self.call_id}"
        return f"{self.status} {self.reason} ({self.get('CSeq')}) call-id={self.call_id}"


def parse_message(data: bytes) -> SipMessage:
    """Parse one complete message (a datagram, or one frame of a TCP stream)."""
    if len(data) > MAX_HEAD_BYTES + MAX_BODY_BYTES:
        raise SipParseError("message too large")
    head, sep, rest = data.partition(b"\r\n\r\n")
    if not sep:
        head, sep, rest = data.partition(b"\n\n")
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SipParseError("message head is not UTF-8") from exc
    raw_lines = text.replace("\r\n", "\n").split("\n")
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    if not raw_lines:
        raise SipParseError("empty message")
    message = _parse_start_line(raw_lines[0])
    # Header folding (RFC 3261 §7.3.1): a line starting with whitespace continues the previous one.
    lines: list[str] = []
    for line in raw_lines[1:]:
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += " " + line.strip()
        elif line.strip():
            lines.append(line)
    for line in lines:
        name, colon, value = line.partition(":")
        if not colon or not _TOKEN.match(name.strip()):
            raise SipParseError(f"malformed header line: {line[:60]!r}", message)
        canonical = _canonical(name)
        value = value.strip()
        if canonical in ("Via", "Contact") and value != "*":
            for part in _split_commas(value):
                message.headers.append((canonical, part))
        else:
            message.headers.append((canonical, value))
    length_text = message.get("Content-Length")
    if length_text is not None:
        try:
            length = int(length_text)
        except ValueError as exc:
            raise SipParseError("Content-Length is not an integer", message) from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise SipParseError("Content-Length out of range", message)
        if len(rest) < length:
            raise SipParseError("body shorter than Content-Length", message)
        message.body = rest[:length]
    else:
        message.body = rest
    if message.is_request:
        _validate_request(message)
    else:
        _validate_response(message)
    return message


def _parse_start_line(line: str) -> SipMessage:
    if line.startswith(SIP_VERSION + " "):
        parts = line.split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError) as exc:
            raise SipParseError(f"bad status line: {line[:60]!r}") from exc
        if not 100 <= status <= 699:
            raise SipParseError(f"status out of range: {status}")
        return SipMessage(status=status, reason=parts[2] if len(parts) > 2 else "")
    parts = line.split(" ")
    if len(parts) != 3 or parts[2] != SIP_VERSION or not _TOKEN.match(parts[0]) or not parts[1]:
        raise SipParseError(f"bad request line: {line[:60]!r}")
    return SipMessage(method=parts[0].upper(), uri=parts[1])


def _validate_request(message: SipMessage) -> None:
    for name in _REQUIRED_REQUEST_HEADERS:
        if not message.get(name):
            raise SipParseError(f"missing {name}", message)
    try:
        number, method = parse_cseq(message.get("CSeq") or "")
    except ValueError as exc:
        raise SipParseError(str(exc), message) from exc
    if method != message.method:
        raise SipParseError("CSeq method does not match the request method", message)
    if number < 0 or number >= 2**31:
        raise SipParseError("CSeq number out of range", message)
    try:
        parse_via(message.get("Via") or "")
        parse_name_addr(message.get("From") or "")
        parse_name_addr(message.get("To") or "")
        parse_uri(message.uri or "")
    except ValueError as exc:
        raise SipParseError(str(exc), message) from exc


def _validate_response(message: SipMessage) -> None:
    for name in ("Via", "Call-ID", "CSeq"):
        if not message.get(name):
            raise SipParseError(f"missing {name}", message)
    try:
        parse_cseq(message.get("CSeq") or "")
    except ValueError as exc:
        raise SipParseError(str(exc), message) from exc


# -- header shapes --------------------------------------------------------------------------------


def _parse_params(text: str) -> dict[str, str | None]:
    params: dict[str, str | None] = {}
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, eq, value = chunk.partition("=")
        params[key.strip().lower()] = value.strip().strip('"') if eq else None
    return params


def _format_params(params: dict[str, str | None]) -> str:
    return "".join(
        f";{key}" if value is None else f";{key}={value}" for key, value in params.items()
    )


@dataclass
class Via:
    """`SIP/2.0/UDP host:port;branch=…;rport` (RFC 3261 §20.42, RFC 3581)."""

    transport: str
    host: str
    port: int | None
    params: dict[str, str | None] = field(default_factory=dict)

    @property
    def branch(self) -> str | None:
        return self.params.get("branch")

    def __str__(self) -> str:
        sent_by = self.host if self.port is None else f"{self.host}:{self.port}"
        return f"SIP/2.0/{self.transport} {sent_by}{_format_params(self.params)}"


def parse_via(value: str) -> Via:
    protocol, _, rest = value.strip().partition(" ")
    pieces = protocol.split("/")
    if len(pieces) != 3 or pieces[0].upper() != "SIP" or pieces[1] != "2.0":
        raise ValueError(f"bad Via protocol: {value[:60]!r}")
    sent_by, _, params = rest.strip().partition(";")
    host, port = _split_host_port(sent_by.strip())
    if not host:
        raise ValueError("Via has no sent-by host")
    return Via(transport=pieces[2].upper(), host=host, port=port, params=_parse_params(params))


def _split_host_port(text: str) -> tuple[str, int | None]:
    if text.startswith("["):  # IPv6 reference
        host, _, tail = text[1:].partition("]")
        port_text = tail[1:] if tail.startswith(":") else ""
    else:
        host, _, port_text = text.partition(":")
    if not port_text:
        return host, None
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError(f"bad port: {text[:60]!r}") from exc
    if not 0 < port < 65536:
        raise ValueError(f"port out of range: {port}")
    return host, port


@dataclass
class SipUri:
    """`sip:user@host:port;params` — the subset a softphone sends."""

    user: str | None
    host: str
    port: int | None = None
    params: dict[str, str | None] = field(default_factory=dict)
    scheme: str = "sip"

    def __str__(self) -> str:
        userinfo = f"{self.user}@" if self.user else ""
        port = f":{self.port}" if self.port else ""
        return f"{self.scheme}:{userinfo}{self.host}{port}{_format_params(self.params)}"


def parse_uri(value: str) -> SipUri:
    text = value.strip()
    scheme, colon, rest = text.partition(":")
    if not colon or scheme.lower() not in ("sip", "sips"):
        raise ValueError(f"not a SIP URI: {text[:60]!r}")
    rest, _, _headers = rest.partition("?")
    address, _, params = rest.partition(";")
    user: str | None = None
    if "@" in address:
        userinfo, _, address = address.rpartition("@")
        user = userinfo.partition(":")[0] or None
    host, port = _split_host_port(address)
    if not host:
        raise ValueError(f"SIP URI has no host: {text[:60]!r}")
    return SipUri(user=user, host=host, port=port, params=_parse_params(params), scheme=scheme)


@dataclass
class NameAddr:
    """`"Display" <sip:…>;tag=…` (From, To, Contact)."""

    uri: str
    display: str = ""
    params: dict[str, str | None] = field(default_factory=dict)

    @property
    def tag(self) -> str | None:
        return self.params.get("tag")

    def __str__(self) -> str:
        display = f'"{self.display}" ' if self.display else ""
        return f"{display}<{self.uri}>{_format_params(self.params)}"


def parse_name_addr(value: str) -> NameAddr:
    text = value.strip()
    if "<" in text:
        display, _, rest = text.partition("<")
        uri, closing, params = rest.partition(">")
        if not closing:
            raise ValueError(f"unterminated '<' in {text[:60]!r}")
        display = display.strip().strip('"')
    else:  # addr-spec form: header params follow the URI directly
        uri, _, params = text.partition(";")
        display = ""
    parse_uri(uri)
    return NameAddr(uri=uri.strip(), display=display, params=_parse_params(params))


def user_of(header_value: str) -> str | None:
    """The user part of a From/To/Contact value, or `None`."""
    try:
        return parse_uri(parse_name_addr(header_value).uri).user
    except ValueError:
        return None


def parse_cseq(value: str) -> tuple[int, str]:
    number, _, method = value.strip().partition(" ")
    try:
        parsed = int(number)
    except ValueError as exc:
        raise ValueError(f"bad CSeq: {value[:40]!r}") from exc
    method = method.strip().upper()
    if not method or not _TOKEN.match(method):
        raise ValueError(f"bad CSeq method: {value[:40]!r}")
    return parsed, method


# -- identifiers ----------------------------------------------------------------------------------


def new_tag() -> str:
    return secrets.token_hex(6)


def new_branch() -> str:
    return BRANCH_COOKIE + secrets.token_hex(10)


def new_call_id(host: str) -> str:
    return f"{secrets.token_hex(12)}@{host}"


# -- responses ------------------------------------------------------------------------------------


def build_response(
    request: SipMessage,
    status: int,
    reason: str | None = None,
    *,
    to_tag: str | None = None,
    headers: list[tuple[str, str]] | None = None,
    body: bytes = b"",
) -> SipMessage:
    """A response that copies Via (all, in order), From, To, Call-ID and CSeq (RFC 3261 §8.2.6)."""
    response = SipMessage(status=status, reason=reason or REASON_PHRASES.get(status, ""))
    for via in request.get_all("Via"):
        response.add("Via", via)
    for name in ("From", "To", "Call-ID", "CSeq"):
        value = request.get(name)
        if value is None:
            continue
        if name == "To" and to_tag and ";tag=" not in value.replace(" ", ""):
            value = f"{value};tag={to_tag}"
        response.add(name, value)
    for name, value in headers or []:
        response.add(name, value)
    response.body = body
    return response


# -- Digest (RFC 2617 §3.2.2, as used by RFC 3261 §22.4) -------------------------------------------


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def digest_ha1(username: str, realm: str, password: str) -> str:
    return _md5(f"{username}:{realm}:{password}")


def digest_response(
    ha1: str,
    *,
    method: str,
    uri: str,
    nonce: str,
    qop: str | None = None,
    nc: str | None = None,
    cnonce: str | None = None,
) -> str:
    ha2 = _md5(f"{method}:{uri}")
    if qop:
        return _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    return _md5(f"{ha1}:{nonce}:{ha2}")


def build_challenge(realm: str, nonce: str, *, stale: bool = False) -> str:
    stale_part = ", stale=true" if stale else ""
    return f'Digest realm="{realm}", nonce="{nonce}", algorithm=MD5, qop="auth"{stale_part}'


def parse_auth_header(value: str) -> tuple[str, dict[str, str]]:
    """`Digest k="v", k=v` → `("Digest", {k: v})`; keys lower-cased."""
    scheme, _, rest = value.strip().partition(" ")
    params: dict[str, str] = {}
    for item in _split_commas(rest):
        key, eq, raw = item.partition("=")
        if not eq:
            continue
        params[key.strip().lower()] = raw.strip().strip('"')
    return scheme, params


def build_authorization(
    *,
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: dict[str, str],
    nc: int = 1,
    cnonce: str | None = None,
) -> str:
    """The `Authorization` value answering a `WWW-Authenticate` challenge (UA side)."""
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    offered_qop = [token.strip() for token in challenge.get("qop", "").split(",") if token.strip()]
    ha1 = digest_ha1(username, realm, password)
    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        "algorithm=MD5",
    ]
    if "auth" in offered_qop:
        nc_text = f"{nc:08x}"
        cnonce = cnonce or secrets.token_hex(8)
        response = digest_response(
            ha1, method=method, uri=uri, nonce=nonce, qop="auth", nc=nc_text, cnonce=cnonce
        )
        parts += ["qop=auth", f"nc={nc_text}", f'cnonce="{cnonce}"']
    else:
        response = digest_response(ha1, method=method, uri=uri, nonce=nonce)
    parts.append(f'response="{response}"')
    if "opaque" in challenge:
        parts.append(f'opaque="{challenge["opaque"]}"')
    return "Digest " + ", ".join(parts)


# -- SDP (RFC 4566 / RFC 3264), audio m-line only ------------------------------------------------


@dataclass(frozen=True)
class SdpMedia:
    """The first audio m-line of a session description."""

    address: str
    port: int
    payload_types: tuple[int, ...]
    rtpmap: dict[int, str]
    ptime: int | None = None
    direction: str = "sendrecv"

    def codec_name(self, payload_type: int) -> str | None:
        name = self.rtpmap.get(payload_type) or STATIC_RTPMAP.get(payload_type)
        return name.split("/")[0].upper() if name else None


def parse_sdp(body: bytes) -> SdpMedia:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SDP is not UTF-8") from exc
    session_address: str | None = None
    media_address: str | None = None
    port: int | None = None
    payload_types: tuple[int, ...] = ()
    rtpmap: dict[int, str] = {}
    ptime: int | None = None
    direction = "sendrecv"
    in_audio = False
    seen_audio = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if len(line) < 2 or line[1] != "=":
            continue
        kind, value = line[0], line[2:]
        if kind == "m":
            if seen_audio:
                in_audio = False
                continue
            fields = value.split()
            in_audio = bool(fields) and fields[0] == "audio"
            if in_audio:
                seen_audio = True
                if len(fields) < 4:
                    raise ValueError("audio m-line too short")
                port = int(fields[1])
                payload_types = tuple(int(pt) for pt in fields[3:])
        elif kind == "c":
            fields = value.split()
            if len(fields) < 3:
                raise ValueError("bad c-line")
            if in_audio:
                media_address = fields[2]
            elif not seen_audio:
                session_address = fields[2]
        elif kind == "a" and (in_audio or not seen_audio):
            name, _, attr = value.partition(":")
            if name == "rtpmap" and in_audio:
                pt_text, _, encoding = attr.partition(" ")
                rtpmap[int(pt_text)] = encoding.strip()
            elif name == "ptime" and in_audio:
                ptime = int(float(attr))
            elif name in ("sendrecv", "sendonly", "recvonly", "inactive"):
                direction = name
    address = media_address or session_address
    if not seen_audio or port is None or address is None:
        raise ValueError("no audio m-line with a connection address")
    return SdpMedia(
        address=address,
        port=port,
        payload_types=payload_types,
        rtpmap=rtpmap,
        ptime=ptime,
        direction=direction,
    )


def build_sdp(
    *,
    address: str,
    port: int,
    payload_types: tuple[int, ...],
    session_id: int,
    version: int = 1,
    ptime: int = 20,
    telephone_event: int | None = None,
) -> bytes:
    formats = list(payload_types) + ([telephone_event] if telephone_event is not None else [])
    lines = [
        "v=0",
        f"o=- {session_id} {version} IN IP4 {address}",
        "s=sim112",
        f"c=IN IP4 {address}",
        "t=0 0",
        f"m=audio {port} RTP/AVP {' '.join(str(pt) for pt in formats)}",
    ]
    for pt in payload_types:
        lines.append(f"a=rtpmap:{pt} {STATIC_RTPMAP[pt]}")
    if telephone_event is not None:
        lines += [
            f"a=rtpmap:{telephone_event} telephone-event/8000",
            f"a=fmtp:{telephone_event} 0-16",
        ]
    lines += [f"a=ptime:{ptime}", "a=sendrecv"]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def choose_codec(offer: SdpMedia, preference: tuple[int, ...] = (PT_PCMA, PT_PCMU)) -> int | None:
    """The answer's codec: PCMA preferred, PCMU accepted (§80.2.1 `rtp.py`), else `None` (488).

    Matched by encoding name, not number alone, so an offer that (wrongly but commonly) maps a
    static number through `a=rtpmap` still resolves.
    """
    wanted = {STATIC_RTPMAP[pt].split("/")[0]: pt for pt in preference}
    offered = {offer.codec_name(pt): pt for pt in offer.payload_types}
    for pt in preference:
        name = STATIC_RTPMAP[pt].split("/")[0]
        if name in offered and offered[name] == wanted[name]:
            return pt
    return None


# -- TCP framing ----------------------------------------------------------------------------------


class StreamFramer:
    """Splits a SIP-over-TCP byte stream into messages by `Content-Length` (RFC 3261 §18.3)."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while True:
            # CRLF keep-alives (RFC 5626 §4.4.1) between messages are skipped.
            while self._buffer[:2] == b"\r\n":
                del self._buffer[:2]
            end = self._buffer.find(b"\r\n\r\n")
            if end < 0:
                if len(self._buffer) > MAX_HEAD_BYTES:
                    raise SipParseError("TCP message head too large")
                return frames
            head = bytes(self._buffer[:end]).decode("utf-8", "replace")
            length = 0
            for line in head.split("\r\n")[1:]:
                name, _, value = line.partition(":")
                if _canonical(name) == "Content-Length":
                    try:
                        length = int(value.strip())
                    except ValueError as exc:
                        raise SipParseError("Content-Length is not an integer") from exc
            if length < 0 or length > MAX_BODY_BYTES:
                raise SipParseError("Content-Length out of range")
            total = end + 4 + length
            if len(self._buffer) < total:
                return frames
            frames.append(bytes(self._buffer[:total]))
            del self._buffer[:total]
