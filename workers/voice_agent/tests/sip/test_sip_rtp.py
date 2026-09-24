"""`rtp.py`: packets, G.711 round-trip bounds, resampling, jitter buffer, stats (80 §80.2.1)."""

from __future__ import annotations

import asyncio
import itertools
import math
import struct

import pytest
from voice_agent.transport.sip.message import PT_PCMA, PT_PCMU
from voice_agent.transport.sip.rtp import (
    FRAME_BYTES,
    JitterBuffer,
    PortAllocator,
    Resampler,
    RtpPacket,
    RtpSession,
    RtpStats,
    decode,
    encode,
    parse_port_range,
    seq_diff,
)


def _sine(freq: float, amplitude: int, samples: int, rate: int = 8000) -> list[int]:
    return [int(amplitude * math.sin(2 * math.pi * freq * n / rate)) for n in range(samples)]


def _pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def _unpack(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


def _snr_db(reference: list[int], other: list[int]) -> float:
    signal = sum(x * x for x in reference)
    noise = sum((x - y) ** 2 for x, y in zip(reference, other, strict=True)) or 1
    return 10 * math.log10(signal / noise)


def test_a_packet_round_trips_and_extensions_padding_and_csrcs_are_parsed_away() -> None:
    packet = RtpPacket(payload_type=8, sequence=65535, timestamp=2**32 - 1, ssrc=7, payload=b"ab")
    assert RtpPacket.parse(packet.to_bytes()) == packet
    # V=2, P=1, X=1, CC=1; one CSRC; a one-word extension; payload "xyz"; 2 bytes of padding.
    raw = (
        struct.pack("!BBHII", 0x80 | 0x20 | 0x10 | 0x01, 0x80 | 0, 5, 160, 9)
        + struct.pack("!I", 42)
        + struct.pack("!HH", 0xBEDE, 1)
        + b"\x00\x00\x00\x00"
        + b"xyz"
        + b"\x00\x02"
    )
    parsed = RtpPacket.parse(raw)
    assert parsed.payload == b"xyz" and parsed.marker and parsed.payload_type == 0
    with pytest.raises(ValueError):
        RtpPacket.parse(b"\x40" + b"\x00" * 11)  # version 1
    with pytest.raises(ValueError):
        RtpPacket.parse(b"\x80\x00")


def test_sequence_arithmetic_wraps() -> None:
    assert seq_diff(0, 65535) == 1
    assert seq_diff(65535, 0) == -1
    assert seq_diff(10, 5) == 5


@pytest.mark.parametrize(("payload_type", "min_snr_db"), [(PT_PCMA, 40.0), (PT_PCMU, 33.0)])
def test_g711_round_trip_error_is_bounded(payload_type: int, min_snr_db: float) -> None:
    """The codec round-trip bound of 80 §80.8.1: a −8 dBFS 1 kHz tone survives within G.711's
    theoretical SNR, and one 20 ms frame is 160 payload bytes."""
    tone = _sine(1000, 12000, 1600)
    payload = encode(_pcm(tone), payload_type)
    assert len(payload) == 1600
    decoded = _unpack(decode(payload, payload_type))
    assert _snr_db(tone, decoded) > min_snr_db
    # Quiet signals keep their shape too (the logarithmic segments are what G.711 is for).
    quiet = _sine(440, 300, 800)
    assert _snr_db(quiet, _unpack(decode(encode(_pcm(quiet), payload_type), payload_type))) > 25


def test_resampling_8k_to_48k_and_back_is_near_transparent() -> None:
    tone = _sine(1000, 10000, 1600)
    up = Resampler(8000, 48000)
    down = Resampler(48000, 8000)
    chunks = [_pcm(tone[i : i + 160]) for i in range(0, 1600, 160)]  # streamed in 20 ms frames
    wide = b"".join(up.convert(chunk) for chunk in chunks)
    assert abs(len(wide) - 6 * 3200) <= 12
    back = _unpack(down.convert(wide))
    assert abs(len(back) - 1600) <= 2
    assert _snr_db(tone[100:1500], back[100:1500]) > 30


def _packet(seq: int) -> RtpPacket:
    return RtpPacket(payload_type=8, sequence=seq, timestamp=seq * 160, ssrc=1, payload=b"x")


def test_the_jitter_buffer_reorders_drops_duplicates_and_late_packets_and_counts_loss() -> None:
    buffer = JitterBuffer(40)  # two frames of depth
    assert buffer.pop() is None  # not primed
    for seq in (65534, 0, 65535):  # out of order, across the wrap
        buffer.push(_packet(seq))
    assert buffer.primed
    assert [buffer.pop().sequence for _ in range(3)] == [65534, 65535, 0]  # type: ignore[union-attr]
    buffer.push(_packet(1))
    buffer.push(_packet(1))
    assert buffer.duplicates == 1
    assert buffer.pop().sequence == 1  # type: ignore[union-attr]
    buffer.push(_packet(0))  # already played: late
    assert buffer.late == 1
    buffer.push(_packet(3))  # 2 is missing
    assert buffer.pop() is None and buffer.lost == 1
    assert buffer.pop().sequence == 3  # type: ignore[union-attr]
    assert buffer.pop() is None and buffer.lost == 1  # underrun is not loss


def test_receive_stats_count_gaps_and_jitter() -> None:
    stats = RtpStats()
    for seq in (10, 11, 13, 14):
        stats.update(_packet(seq), arrival_s=seq * 0.02)
    assert stats.received == 4 and stats.expected == 5 and stats.lost == 1
    assert stats.jitter_ms == pytest.approx(0.0, abs=1e-6)


def test_the_port_allocator_hands_out_even_ports_in_the_range() -> None:
    assert parse_port_range("20000-20199") == (20000, 20199)
    assert parse_port_range("") is None
    with pytest.raises(ValueError):
        parse_port_range("80-90")
    allocator = PortAllocator("20001-20009")
    candidates = allocator.candidates()
    assert candidates and all(port % 2 == 0 and 20002 <= port <= 20008 for port in candidates)
    allocator.claim(candidates[0])
    assert candidates[0] not in allocator.candidates()
    assert PortAllocator(None).candidates() == [0]


async def test_a_session_keeps_sequence_and_timestamp_continuous_and_ignores_other_pts() -> None:
    received: list[RtpPacket] = []
    a = RtpSession(bind_host="127.0.0.1", allocator=PortAllocator(None), payload_type=PT_PCMA)
    b = RtpSession(
        bind_host="127.0.0.1",
        allocator=PortAllocator(None),
        payload_type=PT_PCMA,
        on_packet=lambda packet, _t: received.append(packet),
    )
    await a.open()
    await b.open()
    a.set_remote(("127.0.0.1", b.local_port))
    try:
        for _ in range(10):
            a.send_pcm(b"\x00" * FRAME_BYTES)
        # A telephone-event packet straight at b: counted, ignored.
        assert b.remote is None
        a._transport.sendto(  # type: ignore[union-attr]
            RtpPacket(101, 1, 1, 1, b"\x01\x00\x00\xa0").to_bytes(), ("127.0.0.1", b.local_port)
        )
        for _ in range(50):
            if len(received) >= 10 and b.ignored >= 1:
                break
            await asyncio.sleep(0.01)
    finally:
        a.close()
        b.close()
    assert len(received) == 10 and b.ignored == 1
    for first, second in itertools.pairwise(received):
        assert seq_diff(second.sequence, first.sequence) == 1
        assert (second.timestamp - first.timestamp) % 2**32 == 160
    assert b.remote == ("127.0.0.1", a.local_port)  # latched (symmetric RTP)
