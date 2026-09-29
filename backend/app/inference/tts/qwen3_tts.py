"""`Qwen3TTS` — the real, GPU-default `TTSProvider` (HLD `50-voice-pipeline.md` §2.4, `60-
inference-ops.md`, OWNER DECISION: "use qwen3tts as tts on gpu, I already checked it and it is
very good").

An `httpx` async client of the standalone `workers/tts_qwen3/` worker process — never an in-process
`qwen_tts`/`torch==2.14.0` import (that pin is outside the backend's `asr-gigaam` torch<2.9
ceiling; see `workers/tts_qwen3/README.md` and `/tmp/teamwork-112-maxxing/reports/e14-recon.md`
§1.1, §6 item 3).

**Sentence-chunked synthesis is the caller's job, not this adapter's** (MANAGER RULING 3): Qwen3-TTS
CustomVoice generates a whole utterance per call with no native streaming or cancellation
primitive (recon §1.1 — "no concurrency inside one worker process", "no mechanism to abort an
in-flight `generate_custom_voice()` call"). `stream(text, ...)` therefore treats `text` as **one**
already-split sentence/clause — the deterministic splitter in front of every provider lives in
`app.application.voice` (owned by E14-A) — and issues exactly **one** `/synthesize` request for it;
the returned whole-sentence PCM is then re-chunked here into `<= max_chunk_ms` frames so the port's
"must yield the first chunk without waiting for full synthesis" promise holds at the
*sentence* granularity even though it cannot hold at the *utterance* granularity (see the module's
"HLD gaps" note in this task's report).

`cancel()` closes the in-flight HTTP request/response (`httpx.Response.aclose()`); the worker's own
`await request.is_disconnected()` check (right after it acquires its inference lock,
`tts_qwen3.server`) is what turns that into "dropped, never generated" for a request that had not
yet started, and "the worker keeps computing but we discard the result and never play it, and never
send a further request" for one already in flight — exactly ruling 3's contract.

`instruct` (the English style sentence Qwen3-TTS CustomVoice's only expressive lever) is built by
`app.inference.tts.instruct.build_instruct` from an `EmotionState`. E14-B's `set_emotion()` mutable
seam is gone (MANAGER RULING on E14-B's gap 1, E14 close-out): `TtsVoiceSpec.emotion` is now an
additive field of the port itself (§2.4), so `stream()` reads `voice.emotion` directly — the
neutral default `EmotionState(emotion=CALM, stress_level=0.0)` is used only when `voice.emotion`
is `None` (e.g. a warm-up call with no live `CallerBelief` to read).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

import httpx

from app.application.ports.call_transport import AudioFrame
from app.application.ports.tts import (
    TtsChunk,
    TtsTimeoutError,
    TtsUnavailableError,
    TtsVoiceSpec,
)
from app.domain.caller.emotion import EmotionState
from app.domain.enums import EmotionLabel
from app.inference.errors import InferenceOutOfMemoryError, ModelNotAvailableError
from app.inference.loopback import validate_loopback_base_url
from app.inference.tts.instruct import build_instruct

__all__ = [
    "DEFAULT_ALLOWED_INTERNAL_HOSTS",
    "MODEL_REVISION",
    "OUTPUT_SAMPLE_RATE",
    "TOKENIZER_REPO",
    "TOKENIZER_REVISION",
    "VENDOR_SPEAKERS",
    "Qwen3TTS",
    "TtsQwen3EndpointError",
    "canonical_speaker",
    "validate_tts_qwen3_base_url",
]

logger = logging.getLogger(__name__)

_BYTES_PER_SAMPLE = 2
_MS_PER_S = 1000

#: Pinned exactly like the worker itself (`workers/tts_qwen3/tts_qwen3/server.py`); duplicated
#: here (not imported) because this module must stay importable without the `workers/tts_qwen3`
#: package installed — the two processes never share a venv (see module docstring).
MODEL_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
MODEL_REVISION = "0c0e3051f131929182e2c023b9537f8b1c68adfe"
TOKENIZER_REPO = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
TOKENIZER_REVISION = "7dd38ad4e9bad454aae9cd937d0cd577604fe229"
OUTPUT_SAMPLE_RATE = 24000
#: I8 V0: the speakers the owner evaluated by ear in his TTS lab (serena — the only usable female
#: voice; eric, aiden, uncle_fu — male) plus `ryan` as a spare male; Vivian was rejected by
#: listening. Lower-case, the spelling `qwen_tts` lists them in (it matches case-insensitively).
#: MUST equal `tts_qwen3.server.VENDOR_SPEAKERS` — a gate test compares the two copies.
VENDOR_SPEAKERS: tuple[str, ...] = ("serena", "eric", "aiden", "uncle_fu", "ryan")
_NEUTRAL_EMOTION = EmotionState(emotion=EmotionLabel.CALM, stress_level=0.0)

#: Same default as `LlamaCppClient`'s (`app.inference.llm.llama_cpp_client`): the compose service
#: name every model profile's worker gets, plus loopback. Not literally that module's tuple (this
#: adapter does not import `app.inference.llm` — no cross-provider coupling), same *value*.
DEFAULT_ALLOWED_INTERNAL_HOSTS: tuple[str, ...] = ("tts-qwen3",)


class TtsQwen3EndpointError(RuntimeError):
    """`base_url` is neither loopback nor a configured compose-internal host name (SPEC §41).

    Construction-time only, mirroring `app.inference.llm.errors.ExternalInferenceEndpointError`
    (that module is not imported here: `app.inference.llm` and `app.inference.tts` are sibling
    adapter packages with no reason to depend on each other, D2's "adapters may import each
    other's ports, not each other's internals" spirit)."""


def validate_tts_qwen3_base_url(
    base_url: str, *, allowed_internal_hosts: Sequence[str] = DEFAULT_ALLOWED_INTERNAL_HOSTS
) -> None:
    """SPEC §41: `base_url`'s host must be loopback or a configured compose-internal name.

    E14 close-out, item 5 ("ONE loopback validator"): this used to duplicate
    `app.inference.llm.llama_cpp_client.validate_llm_base_url`'s ~30-line logic because that
    module was outside E14-B's brief's file list. It is now a thin wrapper over the one shared
    `app.inference.loopback.validate_loopback_base_url`, kept importable under this name from this
    module so every existing caller and test is unaffected — behaviour, including the **no DNS
    resolution** rule (a host that would *resolve* to loopback, `127.0.0.1.nip.io`, or merely
    contains the word `localhost`, `localhost.evil.com`, is rejected rather than trusted), is
    unchanged.
    """
    validate_loopback_base_url(
        base_url,
        what="SIM_TTS_QWEN3_BASE_URL",
        allowed_internal_hosts=allowed_internal_hosts,
        error=TtsQwen3EndpointError,
    )


class _VoiceResolver:
    """`TtsVoiceSpec.voice_id` (a SCENARIO-LOGICAL id) -> this provider's NATIVE voice id (E20-G).

    `TtsVoiceSpec.voice_id` carries whatever the scenario's `caller_profile.voice_id` says — it is
    a *logical* casting decision (`ru_female_adult_01`), authored once and played by whichever
    provider the active model profile happens to select (HLD 30 owns the scenario side). Only the
    model profile knows a provider's native ids, so the logical -> native table lives there
    (`tts.voice_map`) with `tts.default_voice` as the answer for anything it does not name.

    A miss is **never** an error: the demo would otherwise be one scenario edit away from a silent
    caller, which is exactly what E20-C's §46 walk hit (`Qwen3TTS.stream()` raised
    `ValueError: TtsVoiceSpec.voice_id='ru_female_adult_01' is not one of the vendor speakers`).
    It is one WARN per `(provider, logical id)` pair — repeated once per turn would be noise — and
    the native id that was actually used is recorded on `CALLER_TTS_STARTED.voice_id_native`.

    Duplicated (not shared) in `app.inference.tts.piper_tts` for the same reason `_chunk_pcm` is:
    two small pure helpers in sibling adapter files, no shared module worth the indirection.
    """

    __slots__ = ("_default", "_map", "_provider_name", "_warned")

    def __init__(
        self, *, provider_name: str, voice_map: Mapping[str, str] | None, default: str
    ) -> None:
        self._provider_name = provider_name
        self._map = dict(voice_map or {})
        self._default = default
        self._warned: set[str] = set()

    def resolve(self, voice_id: str) -> str:
        """The native id for `voice_id`; `self._default` (with one WARN) for anything unmapped."""
        if not voice_id:
            return self._default
        native = self._map.get(voice_id)
        if native is not None:
            return native
        if voice_id not in self._warned:
            self._warned.add(voice_id)
            logger.warning(
                "TTS voice_id %r is not in %s's tts.voice_map; falling back to the profile's "
                "tts.default_voice %r (add the mapping to the active model profile to silence "
                "this)",
                voice_id,
                self._provider_name,
                self._default,
            )
        return self._default


def canonical_speaker(name: str) -> str:
    """`"Serena"` -> `"serena"`: vendor speaker names are matched case-insensitively (I8 V0), so
    an operator's `.env` written for the E14-B spelling keeps working."""
    return name.strip().lower()


def _looks_like_oom(body_text: str) -> bool:
    lowered = body_text.lower()
    return any(
        marker in lowered
        for marker in ("out of memory", "failed to allocate", "cudamalloc failed", "cuda oom")
    )


def _chunk_pcm(pcm: bytes, sample_rate: int, text: str, max_chunk_ms: int) -> list[TtsChunk]:
    """Whole-sentence PCM (one `/synthesize` response) -> `<= max_chunk_ms` `TtsChunk`s.

    Offsets are proportional to byte position within `pcm` (§2.4's "word-proportional fallback"):
    Qwen3-TTS CustomVoice gives no per-word timing (recon §1.1), so `alignment_is_exact` is always
    `False` here, same as every adapter that cannot do better than this.
    """
    if not pcm or not text:
        return []
    bytes_per_ms = max(1, (sample_rate * _BYTES_PER_SAMPLE) // _MS_PER_S)
    chunk_bytes = max(_BYTES_PER_SAMPLE, max_chunk_ms * bytes_per_ms)
    chunk_bytes -= chunk_bytes % _BYTES_PER_SAMPLE
    total_bytes = len(pcm)
    text_len = len(text)
    chunks: list[TtsChunk] = []
    offset = 0
    index = 0
    while offset < total_bytes:
        piece = pcm[offset : offset + chunk_bytes]
        samples = len(piece) // _BYTES_PER_SAMPLE
        audio_ms = (samples * _MS_PER_S) // sample_rate
        start_frac = offset / total_bytes
        end_frac = min(1.0, (offset + len(piece)) / total_bytes)
        chunks.append(
            TtsChunk(
                frame=AudioFrame(
                    pcm=piece,
                    sample_rate=sample_rate,
                    num_channels=1,
                    samples_per_channel=samples,
                    capture_offset_ms=0,
                ),
                text_offset_start=int(start_frac * text_len),
                text_offset_end=int(end_frac * text_len),
                alignment_is_exact=False,
                chunk_index=index,
                audio_ms=audio_ms,
            )
        )
        offset += len(piece)
        index += 1
    # The last chunk always closes on the exact text length, not a rounded fraction (mirrors
    # `FakeTTS`'s "the last chunk always ends at len(text)" rule so a consumer that slices
    # `planned_text[: last.text_offset_end]` never loses the tail character to rounding).
    if chunks:
        last = chunks[-1]
        chunks[-1] = TtsChunk(
            frame=last.frame,
            text_offset_start=last.text_offset_start,
            text_offset_end=text_len,
            alignment_is_exact=False,
            chunk_index=last.chunk_index,
            audio_ms=last.audio_ms,
        )
    return chunks


@dataclass
class _Qwen3TtsStream:
    _provider: Qwen3TTS
    _text: str
    _voice: TtsVoiceSpec
    _request_id: str
    _max_chunk_ms: int
    _speaker: str
    _cancelled: bool = field(default=False, init=False)

    @property
    def request_id(self) -> str:
        return self._request_id

    @property
    def text(self) -> str:
        return self._text

    def __aiter__(self) -> AsyncIterator[TtsChunk]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[TtsChunk]:
        if self._cancelled:
            return
        chunks = await self._provider._synthesize_one_unit(
            self._text, self._speaker, self._request_id, self._max_chunk_ms, self
        )
        for chunk in chunks:
            if self._cancelled:
                return
            yield chunk

    async def cancel(self) -> None:
        """Idempotent. Closes the in-flight `/synthesize` request if one is open (ruling 3): the
        worker drops it if it had not yet started generating, and simply gets its result thrown
        away here if it had — either way, no chunk of this unit is ever yielded after `cancel()`
        returns, and no further `/synthesize` request is ever sent for this stream."""
        if self._cancelled:
            return
        self._cancelled = True
        await self._provider._cancel_request(self._request_id)


class Qwen3TTS:
    """`TTSProvider` over the standalone `tts_qwen3` worker (§2.4)."""

    provider_name = "qwen3_tts"

    def __init__(
        self,
        *,
        base_url: str,
        speaker: str,
        timeout_ms: int = 20_000,
        warmup_timeout_ms: int | None = None,
        allowed_internal_hosts: Sequence[str] = DEFAULT_ALLOWED_INTERNAL_HOSTS,
        client: httpx.AsyncClient | None = None,
        voice_map: Mapping[str, str] | None = None,
        default_voice: str | None = None,
    ) -> None:
        validate_tts_qwen3_base_url(base_url, allowed_internal_hosts=allowed_internal_hosts)
        speaker = canonical_speaker(speaker)
        if speaker not in VENDOR_SPEAKERS:
            raise ValueError(
                f"tts_qwen3_speaker={speaker!r} is not one of the vendor speakers {VENDOR_SPEAKERS}"
            )
        # E20-G: `voice_map`/`default_voice` come from the active model profile's `tts.voice_map` /
        # `tts.default_voice` (`Settings.tts_voice_map`/`tts_default_voice`). `default_voice` falls
        # back to `speaker` (`SIM_TTS_QWEN3_SPEAKER`), which is what this adapter already used for
        # an empty `voice_id`. A `default_voice` that is not a vendor speaker is a CONFIGURATION
        # error and is refused here, at construction — not per utterance.
        resolved_default = canonical_speaker(default_voice) if default_voice else speaker
        if resolved_default not in VENDOR_SPEAKERS:
            raise ValueError(
                f"tts.default_voice={resolved_default!r} is not one of the vendor speakers "
                f"{VENDOR_SPEAKERS} (Qwen3-TTS CustomVoice, recon §1.1)"
            )
        self._voices = _VoiceResolver(
            provider_name=self.provider_name,
            voice_map={
                logical: canonical_speaker(native) for logical, native in (voice_map or {}).items()
            },
            default=resolved_default,
        )
        self._base_url = base_url.rstrip("/")
        self._default_speaker = speaker
        self._timeout_ms = timeout_ms
        #: E20-I: a COLD worker's first `/warm_up` loads the checkpoint onto the GPU and runs one
        #: real generation (~26 s measured for 1.7B on the RTX 3060 Ti), far past a per-request
        #: `timeout_ms` sized for one warm utterance. Under `make up` that made the agent's first
        #: warm-up time out every time and TTS start NOT_READY. The profile's
        #: `warmup.timeout_ms` bounds it instead (`Settings.tts_warmup_timeout_ms`).
        self._warmup_timeout_ms = warmup_timeout_ms if warmup_timeout_ms is not None else timeout_ms
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        #: What the worker's `/health` said it actually serves (`{"model", "revision"}`), once it
        #: has been asked. `None` until then — see `model_version`.
        self._served_version: str | None = None
        #: `request_id -> the open streaming response`, so `cancel()` can abort it out of band
        #: (mirrors `LlamaCppClient._streams`).
        self._pending: dict[str, httpx.Response] = {}

    # -- port properties ----------------------------------------------------------------------

    @property
    def model_version(self) -> str:
        """What the worker **actually serves**, once `/health` has answered (E18-C).

        `SIM_TTS_QWEN3_MODEL` picks the variant (`MODEL_VARIANTS` in `tts_qwen3.server`, 1.7B or
        0.6B) in the *worker's* process, and this adapter's own module constants are the 1.7B
        checkpoint's identity. Reporting those constants therefore meant every `CALLER_TTS_STARTED`
        and every `inference_metrics` row claimed 1.7B even on a machine serving 0.6B — a
        configured guess written into the audit record, which SPEC §27 does not allow.

        `warm_up()` reads `GET /health` and caches `"{model}@{revision}"` from the answer. Before
        that (and if `/health` cannot be reached, which is not worth failing a synthesis over) the
        pinned constants remain the answer: the port's `model_version` is a synchronous property
        and an adapter must not do I/O inside one.
        """
        return self._served_version or f"{MODEL_REPO}@{MODEL_REVISION}"

    async def refresh_model_version(self) -> str:
        """Ask the worker's `/health` what it serves and cache it. Never raises."""
        try:
            response = await self._client.get(
                f"{self._base_url}/health", timeout=self._timeout_ms / 1000
            )
            if response.status_code != 200:
                return self.model_version
            body = response.json()
        except Exception:
            # A worker that cannot answer `/health` still gets to synthesise; the pinned constants
            # stay the answer and the next warm-up tries again.
            return self.model_version
        model = body.get("model") if isinstance(body, dict) else None
        if not isinstance(model, str) or not model:
            return self.model_version
        revision = body.get("revision") if isinstance(body, dict) else None
        self._served_version = f"{model}@{revision}" if isinstance(revision, str) else model
        return self._served_version

    @property
    def output_sample_rate(self) -> int:
        return OUTPUT_SAMPLE_RATE

    # -- the port -------------------------------------------------------------------------------

    async def warm_up(self) -> None:
        try:
            response = await self._client.post(
                f"{self._base_url}/warm_up", timeout=self._warmup_timeout_ms / 1000
            )
        except httpx.TimeoutException as exc:
            raise TtsTimeoutError(
                f"tts_qwen3 warm_up timed out after {self._warmup_timeout_ms}ms"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelNotAvailableError(f"tts_qwen3 worker unreachable: {exc}") from exc
        if response.status_code != 200:
            self._raise_for_status(response.status_code, response.text)
        # After the warm-up, not before: the worker answers `/health` either way, but asking after
        # it has loaded means `loaded: true` and the variant are both settled.
        await self.refresh_model_version()

    def stream(
        self,
        text: str,
        voice: TtsVoiceSpec,
        *,
        request_id: str,
        max_chunk_ms: int = 20,
    ) -> _Qwen3TtsStream:
        # E20-G: `voice.voice_id` is a SCENARIO-LOGICAL id, not a vendor speaker name. It used to
        # be passed through and rejected unless it happened to spell one of the four vendor
        # speakers, which made the shipped demo scenario's `ru_female_adult_01` a hard
        # `ValueError` — a silent caller on the shipped profile (E20-C's §46 walk, item 3). The
        # profile's `tts.voice_map` now maps logical -> native and `tts.default_voice` answers
        # every miss, with one WARN per unmapped id. An unknown logical id never raises.
        speaker = self.native_voice_id(voice.voice_id)
        return _Qwen3TtsStream(self, text, voice, request_id, max_chunk_ms, speaker)

    def native_voice_id(self, voice_id: str) -> str:
        """The vendor CustomVoice speaker this adapter will actually use for `voice_id` (E20-G).

        Public because `CALLER_TTS_STARTED` records BOTH ids: the logical `voice_id` the scenario
        cast, and the `voice_id_native` that was really synthesised (HLD 10 §10.13). Idempotent —
        the WARN of an unmapped id fires once per id, not once per reader.
        """
        return self._voices.resolve(voice_id)

    async def close(self) -> None:
        for response in list(self._pending.values()):
            await response.aclose()
        self._pending.clear()
        if self._owns_client:
            await self._client.aclose()

    # -- internals (called by `_Qwen3TtsStream`) -----------------------------------------------

    async def _synthesize_one_unit(
        self,
        text: str,
        speaker: str,
        request_id: str,
        max_chunk_ms: int,
        stream_obj: _Qwen3TtsStream,
    ) -> list[TtsChunk]:
        emotion = stream_obj._voice.emotion
        body = {
            "text": text,
            "speaker": speaker,
            "language": "Russian",
            "instruct": build_instruct(
                emotion if emotion is not None else _NEUTRAL_EMOTION,
                stream_obj._voice.voice_style,
            ),
            "request_id": request_id,
        }
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/synthesize",
                json=body,
                timeout=self._timeout_ms / 1000,
            ) as response:
                self._pending[request_id] = response
                try:
                    if stream_obj._cancelled:
                        return []
                    if response.status_code != 200:
                        raw = await response.aread()
                        self._raise_for_status(
                            response.status_code, raw.decode("utf-8", errors="replace")
                        )
                    pcm = await response.aread()
                    sample_rate = int(
                        response.headers.get("X-Sample-Rate", str(OUTPUT_SAMPLE_RATE))
                    )
                finally:
                    self._pending.pop(request_id, None)
        except httpx.TimeoutException as exc:
            if stream_obj._cancelled:
                return []
            raise TtsTimeoutError(
                f"tts_qwen3 synthesize timed out after {self._timeout_ms}ms"
            ) from exc
        except httpx.HTTPError as exc:
            if stream_obj._cancelled:
                return []
            raise TtsUnavailableError(f"tts_qwen3 synthesize request failed: {exc}") from exc

        if stream_obj._cancelled:
            return []
        return _chunk_pcm(pcm, sample_rate, text, max_chunk_ms)

    async def _cancel_request(self, request_id: str) -> None:
        response = self._pending.pop(request_id, None)
        if response is not None:
            await response.aclose()

    def _raise_for_status(self, status_code: int, body_text: str) -> None:
        # The worker's own error body never echoes exception text (`tts_qwen3.server`); this
        # adapter does not try to parse it further, only classify by status code.
        if status_code == 499:
            raise TtsUnavailableError("tts_qwen3 dropped the request (client disconnected)")
        if _looks_like_oom(body_text):
            raise InferenceOutOfMemoryError(
                f"tts_qwen3 worker allocation failure (HTTP {status_code})"
            )
        raise TtsUnavailableError(f"tts_qwen3 worker returned HTTP {status_code}")
