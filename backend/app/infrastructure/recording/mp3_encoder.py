"""`LameMp3Encoder` — the `Mp3Encoder` port's real adapter (I5 E40, Q-E16-3 variant b).

Wraps `lameenc`, a compiled binding of the LAME encoder: the container has no system `ffmpeg`/
`lame` binary (only the owner's conda env does, out of scope here — `docs/hld/71-i4-wave4.md`
§71.18.1), and `lameenc` ships LAME itself as a wheel, so `getAudioSegmentMp3` needs no external
process and no `PATH` lookup.

Fixed format (the I5 E40 brief's own decision, not configurable): mono, CBR, 64 kbit/s, at
whatever sample rate the caller passes — this codebase's recordings are always 16 kHz
(`VoiceTurnConfig.sample_rate`), so "the recording's sample rate or 16 kHz" is one number in
practice, but this adapter still encodes at the sample rate it is given rather than hard-coding
16000.

Licence: LAME is LGPL-2.1-or-later; `lameenc`'s own Python binding is MIT (recorded in
`backend/pyproject.toml` next to the dependency and in `docs/hld/71-i4-wave4.md` §71.18.1).
"""

from __future__ import annotations

import lameenc

__all__ = ["LameMp3Encoder"]

_BIT_RATE_KBPS = 64
#: LAME's own quality scale, 0 (best/slowest) to 9 (worst/fastest); 2 is its documented "near-best,
#: recommended" setting and cheap enough for on-demand encoding of a single call turn.
_QUALITY = 2


class LameMp3Encoder:
    """`Mp3Encoder` backed by `lameenc` (bundled LAME, LGPL — see module docstring)."""

    def encode(self, pcm: bytes, *, sample_rate: int, num_channels: int) -> bytes:
        """s16le PCM at `sample_rate`/`num_channels` → a complete MP3 stream (frames, no ID3)."""
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(_BIT_RATE_KBPS)
        encoder.set_in_sample_rate(sample_rate)
        encoder.set_channels(num_channels)
        encoder.set_quality(_QUALITY)
        return bytes(encoder.encode(pcm)) + bytes(encoder.flush())
