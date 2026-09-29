"""SDES-keyed SRTP for the gateway's media (I7 E44; RFC 4568, RFC 3711; ТЗ ¶293, Q-E15-2).

Two halves:

* **SDES negotiation** (pure, no I/O): parse `a=crypto` lines, pick the one suite this stack
  speaks — `AES_CM_128_HMAC_SHA1_80`, the RFC 4568 mandatory-to-implement one, a 30-byte
  `inline:` master key + salt — and decide what a call's media is from the transport its INVITE
  arrived on. Over **TLS** the offer must be `RTP/SAVP` with an acceptable crypto line, else `488`:
  the keys are protected by the signalling, so the media is too. Over **plain UDP/TCP** the media is
  plain RTP: an `RTP/AVP` offer is answered `RTP/AVP` (any `a=crypto` in it ignored — a key sent in
  clear SIP protects nothing), and an `RTP/SAVP` offer is refused `488` (the softphone wants SRTP,
  which this gateway keys only over TLS).
* **`SrtpContext`**: one call's protect / unprotect, both directions, over `pylibsrtp` (libsrtp2).
  No cryptography is implemented here.

A crypto line with an MKI, several keys, or a session parameter other than `WSH` is skipped (not
supported), so an offer that lists a plain `inline:` alternative still negotiates.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from dataclasses import dataclass

import pylibsrtp

from voice_agent.transport.sip.message import SdpMedia

__all__ = [
    "MASTER_KEY_BYTES",
    "PROTO_AVP",
    "PROTO_SAVP",
    "SRTP_SUITE",
    "CryptoAttribute",
    "MediaRejected",
    "SdesAnswer",
    "SrtpContext",
    "SrtpError",
    "accept_answer",
    "negotiate_answer",
    "new_crypto",
    "parse_crypto",
]

SRTP_SUITE = "AES_CM_128_HMAC_SHA1_80"
#: 16-byte AES-128 master key followed by the 14-byte master salt (RFC 4568 §6.2.1).
MASTER_KEY_BYTES = 30
PROTO_AVP = "RTP/AVP"
PROTO_SAVP = "RTP/SAVP"
_TAG = re.compile(r"^[0-9]{1,9}$")
#: Session parameters that change nothing for this stack (RFC 4568 §6.3.7: window size hint).
_HARMLESS_SESSION_PARAMS = ("WSH=",)


class MediaRejected(ValueError):
    """The offer's media security is not acceptable on this signalling transport (`488`)."""


class SrtpError(ValueError):
    """libsrtp refused a packet (authentication failure, replay) or a key."""


@dataclass(frozen=True)
class CryptoAttribute:
    """One `a=crypto:<tag> <suite> inline:<key||salt>` line (RFC 4568 §9.1)."""

    tag: int
    suite: str
    key: bytes

    def sdp_value(self) -> str:
        """The attribute value after `a=crypto:`."""
        inline = base64.b64encode(self.key).decode("ascii")
        return f"{self.tag} {self.suite} inline:{inline}"

    def __repr__(self) -> str:  # never a key in a log line or a traceback
        return f"CryptoAttribute(tag={self.tag}, suite={self.suite!r}, key=<redacted>)"


def new_crypto(tag: int = 1) -> CryptoAttribute:
    """Our side's crypto line: a fresh random master key + salt per call."""
    return CryptoAttribute(tag=tag, suite=SRTP_SUITE, key=secrets.token_bytes(MASTER_KEY_BYTES))


def parse_crypto(value: str) -> CryptoAttribute:
    """Parse one `a=crypto` value; `ValueError` when it is malformed or not supported."""
    fields = value.strip().split()
    if len(fields) < 3:
        raise ValueError("crypto attribute needs a tag, a suite and key parameters")
    tag_text, suite, key_params, *session_params = fields
    if not _TAG.match(tag_text):
        raise ValueError("crypto tag is not 1-9 digits")
    if suite != SRTP_SUITE:
        raise ValueError(f"unsupported crypto suite {suite}")
    for param in session_params:
        if not param.startswith(_HARMLESS_SESSION_PARAMS):
            raise ValueError(f"unsupported crypto session parameter {param.split('=')[0]}")
    if ";" in key_params:
        raise ValueError("more than one master key is not supported")
    method, _, key_info = key_params.partition(":")
    if method != "inline" or not key_info:
        raise ValueError("crypto key method is not inline")
    key_text, *extras = key_info.split("|")
    if len(extras) > 2 or any(":" in extra for extra in extras):
        raise ValueError("an MKI is not supported")
    for extra in extras:  # the optional lifetime: `2^31` or a decimal
        if not re.match(r"^(2\^[0-9]{1,2}|[0-9]{1,20})$", extra):
            raise ValueError("bad master key lifetime")
    try:
        key = base64.b64decode(key_text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("crypto key is not base64") from exc
    if len(key) != MASTER_KEY_BYTES:
        raise ValueError(f"crypto key+salt is {len(key)} bytes, expected {MASTER_KEY_BYTES}")
    return CryptoAttribute(tag=int(tag_text), suite=suite, key=key)


def _first_acceptable(media: SdpMedia) -> CryptoAttribute | None:
    for value in media.crypto:
        try:
            return parse_crypto(value)
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class SdesAnswer:
    """What an SRTP call's answer carries: the offerer's key (inbound) and ours (outbound)."""

    remote: CryptoAttribute
    local: CryptoAttribute


def negotiate_answer(offer: SdpMedia, *, secure_signalling: bool) -> SdesAnswer | None:
    """The answerer's decision on an offer. `None` ⇒ plain RTP; raises `MediaRejected` (`488`).

    `secure_signalling` is whether the offer arrived over TLS.
    """
    protocol = offer.protocol.upper()
    if not secure_signalling:
        if protocol == PROTO_AVP:
            return None
        raise MediaRejected(f"{offer.protocol} over plain SIP: SRTP is keyed over TLS only")
    if protocol != PROTO_SAVP:
        raise MediaRejected(f"{offer.protocol} over TLS: SRTP (RTP/SAVP) is required")
    remote = _first_acceptable(offer)
    if remote is None:
        raise MediaRejected(f"no acceptable a=crypto ({SRTP_SUITE}, inline key, no MKI)")
    return SdesAnswer(remote=remote, local=new_crypto(remote.tag))


def accept_answer(answer: SdpMedia, local: CryptoAttribute) -> CryptoAttribute:
    """The offerer's check of an answer to our SRTP offer: the answerer's key, else `MediaRejected`.

    The answer must be `RTP/SAVP` and carry a crypto line with our tag and suite.
    """
    if answer.protocol.upper() != PROTO_SAVP:
        raise MediaRejected(f"answer is {answer.protocol}, the offer was {PROTO_SAVP}")
    for value in answer.crypto:
        try:
            remote = parse_crypto(value)
        except ValueError:
            continue
        if remote.tag == local.tag and remote.suite == local.suite:
            return remote
    raise MediaRejected(f"answer has no a=crypto for tag {local.tag}")


def _policy(key: bytes, ssrc_type: int) -> pylibsrtp.Policy:
    return pylibsrtp.Policy(
        key=key,
        ssrc_type=ssrc_type,
        srtp_profile=pylibsrtp.Policy.SRTP_PROFILE_AES128_CM_SHA1_80,
    )


class SrtpContext:
    """One call's SRTP: packets we send are protected with our key, packets we receive are
    authenticated and decrypted with the far end's (RFC 4568: each side sends with its own key)."""

    def __init__(self, *, local_key: bytes, remote_key: bytes) -> None:
        try:
            self._tx = pylibsrtp.Session(_policy(local_key, pylibsrtp.Policy.SSRC_ANY_OUTBOUND))
            self._rx = pylibsrtp.Session(_policy(remote_key, pylibsrtp.Policy.SSRC_ANY_INBOUND))
        except (pylibsrtp.Error, ValueError, TypeError) as exc:
            raise SrtpError(f"SRTP key rejected: {exc}") from exc
        self._remote_key = remote_key
        self.failures = 0

    def __repr__(self) -> str:
        return f"SrtpContext(suite={SRTP_SUITE}, failures={self.failures})"

    def protect(self, rtp: bytes) -> bytes:
        try:
            return bytes(self._tx.protect(rtp))
        except pylibsrtp.Error as exc:
            raise SrtpError(f"SRTP protect failed: {exc}") from exc

    def unprotect(self, srtp: bytes) -> bytes:
        try:
            return bytes(self._rx.unprotect(srtp))
        except pylibsrtp.Error as exc:
            self.failures += 1
            raise SrtpError(f"SRTP unprotect failed: {exc}") from exc

    def rekey_inbound(self, remote_key: bytes) -> bool:
        """A re-INVITE's offer may carry a new key (RFC 4568 §7.1.4); `True` when it changed."""
        if remote_key == self._remote_key:
            return False
        try:
            self._rx = pylibsrtp.Session(_policy(remote_key, pylibsrtp.Policy.SSRC_ANY_INBOUND))
        except (pylibsrtp.Error, ValueError, TypeError) as exc:
            raise SrtpError(f"SRTP key rejected: {exc}") from exc
        self._remote_key = remote_key
        return True
