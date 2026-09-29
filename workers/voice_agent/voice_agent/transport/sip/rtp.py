"""RTP send/receive, G.711, resampling and the jitter buffer (HLD 80 §80.2.1 `rtp.py`).

PT 8 (PCMA) preferred, PT 0 (PCMU) accepted, `telephone-event` (any other PT) ignored; ptime
20 ms (160 samples, 8 kHz); jitter buffer `SIM_SIP_JITTER_MS` (default 40); G.711 and the
8 kHz ↔ 48 kHz resampler are stdlib `audioop` (Python 3.12 still ships it — deprecated, removed in
3.13; the workspace pins `>=3.12,<3.13`, and a 3.13 move needs an in-tree replacement first).

Ports come from `SIM_SIP_RTP_PORT_RANGE` ("20000-20199": 100 concurrent calls at an even RTP port
each, the odd neighbour reserved for RTCP, which this stack does not send). `port_range=None`
binds an ephemeral port — what the gate tests use.

SRTP (I7 E44): a session given an `SrtpContext` (`srtp.py`, libsrtp) protects every packet it sends
and authenticates + decrypts every packet it receives; one that fails is dropped and counted, and
never latches the far address. `require_srtp` (a call whose INVITE came over TLS) makes the session
send and accept nothing until that context is set — no plaintext fallback.
"""

from __future__ import annotations

import asyncio
import logging
import random
import struct
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass

from voice_agent.transport.sip.message import PT_PCMA, PT_PCMU
from voice_agent.transport.sip.srtp import SrtpContext, SrtpError

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import audioop

__all__ = [
    "CLOCK_RATE",
    "FRAME_BYTES",
    "SAMPLES_PER_FRAME",
    "JitterBuffer",
    "PortAllocator",
    "Resampler",
    "RtpPacket",
    "RtpSession",
    "RtpStats",
    "decode",
    "encode",
    "parse_port_range",
]

logger = logging.getLogger(__name__)

RTP_VERSION = 2
CLOCK_RATE = 8000
PTIME_MS = 20
SAMPLES_PER_FRAME = CLOCK_RATE * PTIME_MS // 1000  # 160
FRAME_BYTES = SAMPLES_PER_FRAME * 2  # 320 bytes of s16le
_SEQ_MOD = 1 << 16
_TS_MOD = 1 << 32


# -- packets --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RtpPacket:
    """One RTP packet (RFC 3550 §5.1); CSRCs, extensions and padding are parsed away."""

    payload_type: int
    sequence: int
    timestamp: int
    ssrc: int
    payload: bytes
    marker: bool = False

    def to_bytes(self) -> bytes:
        first = RTP_VERSION << 6
        second = (0x80 if self.marker else 0) | (self.payload_type & 0x7F)
        header = struct.pack(
            "!BBHII",
            first,
            second,
            self.sequence % _SEQ_MOD,
            self.timestamp % _TS_MOD,
            self.ssrc,
        )
        return header + self.payload

    @classmethod
    def parse(cls, data: bytes) -> RtpPacket:
        if len(data) < 12:
            raise ValueError("RTP packet shorter than its fixed header")
        first, second, sequence, timestamp, ssrc = struct.unpack("!BBHII", data[:12])
        if first >> 6 != RTP_VERSION:
            raise ValueError("not RTP version 2")
        offset = 12 + 4 * (first & 0x0F)
        if first & 0x10:  # header extension
            if len(data) < offset + 4:
                raise ValueError("truncated RTP extension")
            (words,) = struct.unpack("!H", data[offset + 2 : offset + 4])
            offset += 4 + 4 * words
        end = len(data)
        if first & 0x20:  # padding
            end -= data[-1]
        if offset > end:
            raise ValueError("truncated RTP packet")
        return cls(
            payload_type=second & 0x7F,
            sequence=sequence,
            timestamp=timestamp,
            ssrc=ssrc,
            payload=bytes(data[offset:end]),
            marker=bool(second & 0x80),
        )


def seq_diff(a: int, b: int) -> int:
    """`a - b` in 16-bit sequence space, signed (wrap-around safe)."""
    diff = (a - b) % _SEQ_MOD
    return diff - _SEQ_MOD if diff >= _SEQ_MOD // 2 else diff


# -- codecs ---------------------------------------------------------------------------------------


def encode(pcm: bytes, payload_type: int) -> bytes:
    """8 kHz s16le mono → G.711 payload."""
    if payload_type == PT_PCMA:
        return audioop.lin2alaw(pcm, 2)
    if payload_type == PT_PCMU:
        return audioop.lin2ulaw(pcm, 2)
    raise ValueError(f"unsupported payload type {payload_type}")


def decode(payload: bytes, payload_type: int) -> bytes:
    """G.711 payload → 8 kHz s16le mono."""
    if payload_type == PT_PCMA:
        return audioop.alaw2lin(payload, 2)
    if payload_type == PT_PCMU:
        return audioop.ulaw2lin(payload, 2)
    raise ValueError(f"unsupported payload type {payload_type}")


def silence_payload(payload_type: int) -> bytes:
    return encode(b"\x00" * FRAME_BYTES, payload_type)


class Resampler:
    """Streaming mono s16le resampler over `audioop.ratecv` (state kept between chunks)."""

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self.src_rate = src_rate
        self.dst_rate = dst_rate
        self._state: tuple[int, tuple[tuple[int, int], ...]] | None = None

    def convert(self, pcm: bytes) -> bytes:
        if self.src_rate == self.dst_rate or not pcm:
            return pcm
        out, self._state = audioop.ratecv(pcm, 2, 1, self.src_rate, self.dst_rate, self._state)
        return out


def rms(pcm: bytes) -> int:
    return audioop.rms(pcm, 2) if pcm else 0


# -- jitter buffer --------------------------------------------------------------------------------


class JitterBuffer:
    """Reorders packets by sequence number and releases one per ptime after `depth_ms` of priming.

    Playout starts once `depth_ms` of audio is waiting (40 ms = two frames). `pop()` is then
    called on the playout clock (every 20 ms): it returns the next packet in sequence,
    or `None` for a gap (a packet counted lost once a later one is already waiting) or an underrun
    (nothing waiting; the position is kept so a slightly late packet still plays). A packet older
    than the playout position is late and dropped; a repeated one is a duplicate and dropped.
    """

    def __init__(self, depth_ms: int = 40, *, ptime_ms: int = PTIME_MS, capacity: int = 50) -> None:
        self.depth_frames = max(0, depth_ms // ptime_ms)
        self._capacity = capacity
        self._packets: dict[int, RtpPacket] = {}
        self._next: int | None = None
        self.primed = False
        self.late = 0
        self.duplicates = 0
        self.lost = 0
        self.played = 0

    def __len__(self) -> int:
        return len(self._packets)

    def push(self, packet: RtpPacket) -> None:
        seq = packet.sequence
        if self._next is None:
            self._next = seq
        elif seq_diff(seq, self._next) < 0:
            self.late += 1
            return
        if seq in self._packets:
            self.duplicates += 1
            return
        self._packets[seq] = packet
        if len(self._packets) > self._capacity:  # the far end jumped: resynchronise
            self._next = min(self._packets, key=lambda s: seq_diff(s, seq))
            for stale in [s for s in self._packets if seq_diff(s, self._next) < 0]:
                del self._packets[stale]
        if not self.primed and len(self._packets) >= max(1, self.depth_frames):
            self.primed = True

    def pop(self) -> RtpPacket | None:
        if not self.primed or self._next is None:
            return None
        packet = self._packets.pop(self._next, None)
        if packet is not None:
            self._next = (self._next + 1) % _SEQ_MOD
            self.played += 1
            return packet
        if self._packets:  # a gap with later packets waiting: that one is lost
            self.lost += 1
            self._next = (self._next + 1) % _SEQ_MOD
        return None


# -- statistics -----------------------------------------------------------------------------------


class RtpStats:
    """Receive statistics: count, sequence gaps (loss), RFC 3550 §6.4.1 interarrival jitter."""

    def __init__(self) -> None:
        self.received = 0
        self.first_seq: int | None = None
        self.highest_seq: int | None = None
        self.out_of_order = 0
        self._jitter = 0.0
        self._last_transit: float | None = None

    def update(self, packet: RtpPacket, arrival_s: float) -> None:
        self.received += 1
        if self.first_seq is None:
            self.first_seq = self.highest_seq = packet.sequence
        else:
            assert self.highest_seq is not None
            if seq_diff(packet.sequence, self.highest_seq) > 0:
                self.highest_seq = packet.sequence
            else:
                self.out_of_order += 1
        transit = arrival_s * CLOCK_RATE - packet.timestamp
        if self._last_transit is not None:
            delta = abs(transit - self._last_transit)
            self._jitter += (delta - self._jitter) / 16.0
        self._last_transit = transit

    @property
    def expected(self) -> int:
        if self.first_seq is None or self.highest_seq is None:
            return 0
        return seq_diff(self.highest_seq, self.first_seq) + 1

    @property
    def lost(self) -> int:
        return max(0, self.expected - self.received)

    @property
    def jitter_ms(self) -> float:
        return self._jitter * 1000.0 / CLOCK_RATE


# -- ports and sockets ----------------------------------------------------------------------------


def parse_port_range(text: str | None) -> tuple[int, int] | None:
    """`"20000-20199"` → `(20000, 20199)`; empty/None → `None` (ephemeral ports)."""
    if not text:
        return None
    low_text, _, high_text = text.partition("-")
    low, high = int(low_text), int(high_text or low_text)
    if not 1024 <= low <= high <= 65535:
        raise ValueError(f"bad RTP port range: {text!r}")
    return low, high


class _RtpProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: RtpSession) -> None:
        self._session = session

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._session._on_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.debug("RTP socket error: %s", exc)


class PortAllocator:
    """Hands out even RTP ports from the configured range, skipping ones already bound."""

    def __init__(self, port_range: str | None) -> None:
        self._range = parse_port_range(port_range)
        self._in_use: set[int] = set()
        self._cursor = 0

    def candidates(self) -> list[int]:
        if self._range is None:
            return [0]
        low, high = self._range
        start = low + (low % 2)
        ports = [p for p in range(start, high + 1, 2) if p not in self._in_use]
        if not ports:
            return []
        self._cursor %= len(ports)
        ordered = ports[self._cursor :] + ports[: self._cursor]
        self._cursor += 1
        return ordered

    def claim(self, port: int) -> None:
        if self._range is not None:
            self._in_use.add(port)

    def release(self, port: int) -> None:
        self._in_use.discard(port)


class RtpSession:
    """One RTP port, one far end, one negotiated codec.

    Outbound packets carry this session's own SSRC, and a sequence number and timestamp that
    advance by exactly 1 and 160 per frame — continuity is a property of the sender, whatever the
    source of the audio. Inbound packets with a PT other than the negotiated one (e.g.
    `telephone-event`) are counted and ignored. The far end's address is taken from its SDP and
    then *latched* to the source of the first packet received (symmetric RTP), which is what makes
    a softphone behind NAT work.
    """

    def __init__(
        self,
        *,
        bind_host: str,
        allocator: PortAllocator,
        payload_type: int,
        on_packet: Callable[[RtpPacket, float], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bind_host = bind_host
        self._allocator = allocator
        self.payload_type = payload_type
        self.on_packet = on_packet
        self._clock = clock
        self._transport: asyncio.DatagramTransport | None = None
        self.local_port = 0
        self.remote: tuple[str, int] | None = None
        self._latched = False
        self.ssrc = random.getrandbits(32)
        self._seq = random.getrandbits(16)
        self._ts = random.getrandbits(32)
        self.sent = 0
        self.ignored = 0
        self.stats = RtpStats()
        #: I7 E44: the call's SRTP context (set once both keys are known) and whether it is
        #: mandatory; `srtp_dropped` counts inbound packets that failed SRTP authentication.
        self.srtp: SrtpContext | None = None
        self.require_srtp = False
        self.srtp_dropped = 0

    async def open(self) -> int:
        loop = asyncio.get_running_loop()
        last_error: OSError | None = None
        for port in self._allocator.candidates():
            try:
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: _RtpProtocol(self), local_addr=(self._bind_host, port)
                )
            except OSError as exc:
                last_error = exc
                continue
            self._transport = transport
            self.local_port = transport.get_extra_info("sockname")[1]
            self._allocator.claim(self.local_port)
            return self.local_port
        raise OSError(f"no free RTP port in the configured range ({last_error})")

    def set_remote(self, address: tuple[str, int]) -> None:
        if not self._latched:
            self.remote = address

    def send_payload(self, payload: bytes, *, marker: bool = False) -> RtpPacket | None:
        """Send one 20 ms frame; returns the packet sent (or `None` with no far end yet)."""
        packet = RtpPacket(
            payload_type=self.payload_type,
            sequence=self._seq,
            timestamp=self._ts,
            ssrc=self.ssrc,
            payload=payload,
            marker=marker,
        )
        self._seq = (self._seq + 1) % _SEQ_MOD
        self._ts = (self._ts + SAMPLES_PER_FRAME) % _TS_MOD
        if self._transport is None or self.remote is None:
            return None
        data = packet.to_bytes()
        if self.srtp is not None:
            data = self.srtp.protect(data)
        elif self.require_srtp:
            return None  # never plaintext on a call that must be encrypted
        self._transport.sendto(data, self.remote)
        self.sent += 1
        return packet

    def send_pcm(self, pcm: bytes, *, marker: bool = False) -> RtpPacket | None:
        return self.send_payload(encode(pcm, self.payload_type), marker=marker)

    def _on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        arrival = self._clock()
        if self.srtp is not None:
            try:
                data = self.srtp.unprotect(data)
            except SrtpError:
                self.srtp_dropped += 1
                self.ignored += 1
                return
        elif self.require_srtp:
            self.ignored += 1
            return
        try:
            packet = RtpPacket.parse(data)
        except ValueError:
            self.ignored += 1
            return
        if packet.payload_type != self.payload_type:
            self.ignored += 1
            return
        if not self._latched:
            self.remote = addr
            self._latched = True
        self.stats.update(packet, arrival)
        if self.on_packet is not None:
            try:
                self.on_packet(packet, arrival)
            except Exception:
                logger.exception("RTP packet handler failed")

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            self._allocator.release(self.local_port)
