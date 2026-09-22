"""`python -m voice_agent.tools.inject` — the mic-less demo CLI (E20 row "audio-injection tool",
ruling R8; `docs/RUNBOOK.md`, `docs/DOD_WALK.md`).

Packages `voice_agent.transport.headless_client.HeadlessTraineeClient` (E19, HLD 60 §7.4) as
something an operator (or `docs/DOD_WALK.md`'s §46 walk) can run from a shell with no sound card
and no browser: it logs in as the seeded `trainee` account exactly like a browser would (username
`trainee`, `SIM_SEED_TRAINEE_PASSWORD` from the environment — never a literal, SPEC §41), mints a
LiveKit token via `POST /api/v1/sessions/{id}/voice-token` (D9 — this IS a REST client, not the
voice agent, so D9's "no REST from the agent" does not apply here), joins the session's room, plays
one or more WAVs at real-time pace as the trainee's "microphone", and prints what the trainee's own
realtime WebSocket connection (`GET /api/v1/ws/sessions/{id}`, HLD 40 §40.1-§40.3) reports about
each turn.

**Trap, read before changing this file (`reports/e19-e.md` E2/E3):** the session must already be
RINGING or CONNECTED before `createVoiceToken` succeeds (it 409s a `READY` session and a session
whose call has ended) — start the call (`answerCall` or just let it ring) before running this tool,
and only once the four `voice:health:{vad,asr,llm,tts}` keys are READY (`make preflight`), or the
caller LLM/TTS simply has nothing to answer with.

**Why there is no literal caller transcript (a deliberate, documented reading — see the task
report's "HLD gaps"):** the trainee-facing WebSocket redacts `CALLER_TTS_STARTED.text_sent_to_tts`
down to `{call_id, turn_index, at_offset_ms}` (HLD 40 §40.4 row 12,
`backend/app/application/realtime/redaction.py:154-155`) — the same boundary R1 of this epic
closes for the REST list endpoints. Printing the caller's words to a client authenticated as the
TRAINEE would reopen exactly that leak, so this tool does not do it. What it prints instead is what
the trainee's own connection legitimately receives: `ASR_FINAL.text` (the trainee's OWN WAV,
transcribed — a sanity check that the pipeline heard the right file), and the redacted
`CALLER_TTS_STARTED`/`CALLER_TTS_ENDED` timing that lets an operator see the caller replying without
seeing what they said.

Every network boundary here is dependency-injected (`http_client_factory`, `voice_client_factory`,
`event_stream_factory`) so `run_injection`'s turn loop — the part with real logic — is testable
against a fake trainee-voice client and a canned WebSocket event feed, with no LiveKit server and
no backend process (the gate test). The real `event_stream_factory` uses the `websockets` package,
already resolved in `uv.lock` as a transitive dependency of `uvicorn`'s standard extra (every
workspace member shares one venv, `Makefile`'s `deps` target) — not a `workers/voice_agent`
dependency this file's owner (E20-B) is allowed to add explicitly (that pyproject.toml is outside
this task's FILES); a missing/renamed `websockets` therefore fails with a clear `ImportError`
message rather than silently.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TextIO
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from app.config.settings import read_env_value

__all__ = [
    "ApiError",
    "TraineeVoiceClient",
    "TurnSpec",
    "VoiceToken",
    "fetch_voice_token",
    "login",
    "main",
    "run_injection",
]

DEFAULT_API_BASE_URL = "http://127.0.0.1:8100"
TRAINEE_USERNAME = "trainee"
TRAINEE_PASSWORD_ENV = "SIM_SEED_TRAINEE_PASSWORD"  # an env var NAME, not a secret literal
DEFAULT_CALLER_REPLY_TIMEOUT_S = 20.0


class ApiError(RuntimeError):
    """A REST call the CLI depends on did not answer the way it needs (never a stack trace to a
    trainee-facing terminal — this is an operator tool, so the message is the whole point)."""


@dataclass(frozen=True)
class VoiceToken:
    """`VoiceTokenResponse` (`openapi.yaml`, `backend/app/api/schemas/voice.py`), field by field."""

    token: str
    livekit_url: str
    room_name: str
    participant_identity: str
    expires_at: str


@dataclass(frozen=True)
class TurnSpec:
    """One WAV to publish as one trainee turn. `id` is this tool's own label, never the server's
    `turn_index` (the server assigns that; see `run_injection`'s docstring on correlation)."""

    id: str
    path: Path


class TraineeVoiceClient(Protocol):
    """The slice of `HeadlessTraineeClient` this CLI drives — small enough to fake in a test with
    no LiveKit SDK anywhere, which is what the gate test does."""

    async def connect(self) -> None: ...

    async def publish_wav(self, path: Path, *, turn_id: str, realtime: bool = True) -> Any: ...

    async def close(self) -> None: ...


# -------------------------------------------------------------------------------------------
# REST: login as the trainee, then mint a voice token (SPEC §41 - a login exactly a browser does)
# -------------------------------------------------------------------------------------------


async def login(client: httpx.AsyncClient, *, base_url: str, username: str, password: str) -> str:
    """`POST /api/v1/auth/login` -> the bearer `access_token` (`openapi.yaml`'s `loginUser`)."""
    response = await client.post(
        f"{base_url}/api/v1/auth/login", json={"username": username, "password": password}
    )
    if response.status_code != 200:
        raise ApiError(f"login as {username!r} failed: HTTP {response.status_code} {response.text}")
    return str(response.json()["access_token"])


async def fetch_voice_token(
    client: httpx.AsyncClient, *, base_url: str, session_id: str, access_token: str
) -> VoiceToken:
    """`POST /api/v1/sessions/{id}/voice-token` (`createVoiceToken`) — 409s until the call is
    RINGING or CONNECTED (this module's docstring's trap)."""
    response = await client.post(
        f"{base_url}/api/v1/sessions/{session_id}/voice-token",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code != 200:
        raise ApiError(
            f"voice-token for session {session_id} failed: "
            f"HTTP {response.status_code} {response.text}"
        )
    data = response.json()
    return VoiceToken(
        token=data["token"],
        livekit_url=data["livekit_url"],
        room_name=data["room_name"],
        participant_identity=data["participant_identity"],
        expires_at=str(data["expires_at"]),
    )


def _ws_url(api_base_url: str, session_id: str, access_token: str) -> str:
    """`GET /api/v1/ws/sessions/{id}?token=...` (HLD 40 §40.1), from the REST base URL's host."""
    parts = urlsplit(api_base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    query = urlencode({"token": access_token})
    return urlunsplit((scheme, parts.netloc, f"/api/v1/ws/sessions/{session_id}", query, ""))


# -------------------------------------------------------------------------------------------
# The real event stream — `websockets`, see this module's docstring on why it is not a static
# top-level import: kept inside the factory so importing this module never requires it.
# -------------------------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _open_real_event_stream(ws_url: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - always present via uvicorn[standard]
        raise ApiError(
            "the `websockets` package is not importable in this venv (normally a transitive "
            "dependency of uvicorn's standard extra, resolved by `make deps`)"
        ) from exc

    async with websockets.connect(ws_url) as connection:
        await connection.send(json.dumps({"type": "resume", "after_seq_no": 0}))

        async def _frames() -> AsyncIterator[dict[str, Any]]:
            async for raw in connection:
                yield json.loads(raw)

        yield _frames()


def _build_real_voice_client(*, url: str, token: str, room: str) -> TraineeVoiceClient:
    """`HeadlessTraineeClient` — imported here, not at module scope, matching `voice_agent.main`'s
    own convention of never importing a `transport/` class outside a factory (D9's boundary is
    about the `livekit` SDK itself, which this file never imports either way — see
    `workers/voice_agent/tests/test_transport_boundary.py`)."""
    from voice_agent.transport.headless_client import HeadlessTraineeClient

    return HeadlessTraineeClient(url=url, token=token, room=room)


# -------------------------------------------------------------------------------------------
# Turn corpus: --wav (repeatable) or --turns turns.jsonl (same shape as
# benchmarks/data/e2e/turns.jsonl: one {"id", "path", ...} object per line, "path" relative to the
# jsonl file's own directory unless absolute — this tool reads only "id" and "path").
# -------------------------------------------------------------------------------------------


def turns_from_wavs(paths: Sequence[Path]) -> list[TurnSpec]:
    return [TurnSpec(id=f"turn-{i}", path=path) for i, path in enumerate(paths, start=1)]


def turns_from_jsonl(path: Path) -> list[TurnSpec]:
    turns: list[TurnSpec] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        wav_path = Path(row["path"])
        if not wav_path.is_absolute():
            wav_path = path.parent / wav_path
        turns.append(TurnSpec(id=str(row.get("id", f"turn-{len(turns) + 1}")), path=wav_path))
    return turns


# -------------------------------------------------------------------------------------------
# The turn loop: publish each WAV, print what the trainee's own event stream reports about it.
# -------------------------------------------------------------------------------------------


@dataclass
class _TurnTracker:
    """Correlates published WAVs with `CALLER_TTS_ENDED` events **by order, not by ID**: a call
    processes one turn at a time (`TurnPipeline`), so the Nth `CALLER_TTS_ENDED` is the reply to
    the Nth WAV sent — unless the VAD splits one WAV into more than one `USER_SPEECH_ENDED` (seen
    for real in `reports/e19-e.md` E3.2, "3 VAD splits"), in which case this counts low and
    `--wait-caller` can time out on a turn that already finished. A demo convenience, not a
    benchmark instrument (`benchmarks/benchmark_e2e.py` is that, and reads the event log directly).
    """

    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    completed_count: int = 0
    pending_user_speech_end_offsets_ms: list[int] = field(default_factory=list)

    async def note_caller_turn_ended(self) -> None:
        async with self.condition:
            self.completed_count += 1
            self.condition.notify_all()

    async def wait_for_count(self, target: int, *, timeout_s: float) -> bool:
        async def _wait() -> None:
            async with self.condition:
                await self.condition.wait_for(lambda: self.completed_count >= target)

        try:
            await asyncio.wait_for(_wait(), timeout=timeout_s)
        except TimeoutError:
            return False
        return True


async def _consume_events(
    frames: AsyncIterator[dict[str, Any]], tracker: _TurnTracker, out: TextIO
) -> None:
    """Print the trainee-visible events a turn produces; see this module's docstring for why the
    caller's TTS text is never among them."""
    async for frame in frames:
        if frame.get("type") != "event":
            continue
        event_type = frame.get("event_type")
        payload = frame.get("payload") or {}
        if event_type == "ASR_FINAL":
            print(f'   heard (trainee speech): "{payload.get("text", "")}"', file=out)
        elif event_type == "USER_SPEECH_ENDED":
            offset = payload.get("at_offset_ms")
            if isinstance(offset, int):
                tracker.pending_user_speech_end_offsets_ms.append(offset)
        elif event_type == "CALLER_TTS_STARTED":
            print(
                f"   caller replying (turn_index={payload.get('turn_index')}, "
                f"at_offset_ms={payload.get('at_offset_ms')}) "
                "- text withheld from OPERATOR_112 by design (HLD 40 §40.4 row 12)",
                file=out,
            )
            _print_speech_end_to_first_audio(payload, tracker, out)
        elif event_type == "CALLER_TTS_ENDED":
            print(f"   caller done (completed={payload.get('completed')})", file=out)
            await tracker.note_caller_turn_ended()
        elif event_type == "CALLER_UTTERANCE_INTERRUPTED":
            print(f"   barge-in: cutoff_latency_ms={payload.get('cutoff_latency_ms')}", file=out)


def _print_speech_end_to_first_audio(
    payload: dict[str, Any], tracker: _TurnTracker, out: TextIO
) -> None:
    """SPEC §27's `speech_end_to_first_audio_ms`, read from this connection's own event log (the
    same "authority is the log, not a wall clock" reading `headless_client.py`'s docstring states)
    - not the number `benchmark_e2e.py` publishes, only a live cross-check for the demo operator."""
    if not tracker.pending_user_speech_end_offsets_ms:
        return
    start_ms = tracker.pending_user_speech_end_offsets_ms.pop(0)
    end_ms = payload.get("at_offset_ms")
    if not isinstance(end_ms, int):
        return
    delta = end_ms - start_ms
    if delta > 0:
        print(f"   speech_end_to_first_audio_ms: {delta}", file=out)
    else:
        print(
            f"   speech_end_to_first_audio_ms: not derivable ({delta} ms over this transport; "
            "see E20 R13)",
            file=out,
        )


async def run_injection(
    *,
    api_base_url: str,
    session_id: str,
    turns: Sequence[TurnSpec],
    wait_caller: bool,
    password: str,
    username: str = TRAINEE_USERNAME,
    out: TextIO | None = None,
    http_client_factory: Callable[[], httpx.AsyncClient] = httpx.AsyncClient,
    voice_client_factory: Callable[..., TraineeVoiceClient] = _build_real_voice_client,
    event_stream_factory: Callable[
        [str], contextlib.AbstractAsyncContextManager[AsyncIterator[dict[str, Any]]]
    ] = _open_real_event_stream,
    caller_reply_timeout_s: float = DEFAULT_CALLER_REPLY_TIMEOUT_S,
) -> int:
    """Log in, mint a voice token, join the room, publish every turn, print what came back.

    `wait_caller=True` blocks after each WAV until that turn's `CALLER_TTS_ENDED` is seen (or
    `caller_reply_timeout_s` elapses) before sending the next one - useful for a scripted interview
    where the next question depends on being heard, not stepped on. The default fires each WAV at
    its own realtime pace and moves straight to the next one, which is what a barge-in demo needs.
    """
    out = out if out is not None else sys.stdout
    base_url = api_base_url.rstrip("/")
    async with http_client_factory() as client:
        access_token = await login(client, base_url=base_url, username=username, password=password)
        voice_token = await fetch_voice_token(
            client, base_url=base_url, session_id=session_id, access_token=access_token
        )

    print(
        f"joined as {voice_token.participant_identity!r} in room {voice_token.room_name!r} "
        f"({voice_token.livekit_url})",
        file=out,
    )
    voice_client = voice_client_factory(
        url=voice_token.livekit_url, token=voice_token.token, room=voice_token.room_name
    )
    await voice_client.connect()
    tracker = _TurnTracker()
    try:
        ws_url = _ws_url(base_url, session_id, access_token)
        async with event_stream_factory(ws_url) as frames:
            consumer = asyncio.create_task(_consume_events(frames, tracker, out))
            try:
                for index, turn in enumerate(turns, start=1):
                    print(
                        f"-> sending {turn.path.name} (turn {index}/{len(turns)}, id={turn.id})",
                        file=out,
                    )
                    await voice_client.publish_wav(turn.path, turn_id=turn.id)
                    if wait_caller:
                        answered = await tracker.wait_for_count(
                            index, timeout_s=caller_reply_timeout_s
                        )
                        if not answered:
                            print(
                                f"   (timed out waiting for the caller's reply to turn {index})",
                                file=out,
                            )
            finally:
                consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer
    finally:
        await voice_client.close()
    return 0


# -------------------------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m voice_agent.tools.inject",
        description=(
            "Mic-less demo: log in as the seeded trainee, join SESSION's LiveKit room, and play "
            "WAV(s) at real-time pace, printing what the trainee's own event stream reports "
            "(R8, docs/RUNBOOK.md)."
        ),
    )
    parser.add_argument(
        "--api",
        default=DEFAULT_API_BASE_URL,
        help=f"backend API base URL (default: {DEFAULT_API_BASE_URL})",
    )
    parser.add_argument(
        "--session", required=True, help="session id (UUID); its call must already be ringing"
    )
    parser.add_argument(
        "--wav",
        action="append",
        dest="wavs",
        type=Path,
        default=[],
        metavar="PATH",
        help="a 16 kHz mono 16-bit WAV to publish as one trainee turn; repeatable",
    )
    parser.add_argument(
        "--turns",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "a turns.jsonl file instead of --wav (same shape as "
            "benchmarks/data/e2e/turns.jsonl: one {id, path, ...} object per line)"
        ),
    )
    parser.add_argument(
        "--wait-caller",
        action="store_true",
        help="wait for the caller's reply to finish before sending the next WAV (default: no)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if bool(args.wavs) == bool(args.turns):
        parser.error("pass either one or more --wav, or --turns, not both and not neither")

    turns = turns_from_jsonl(args.turns) if args.turns else turns_from_wavs(args.wavs)
    if not turns:
        parser.error("no turns to send")

    # Environment first, then `.env` (`SIM_ENV_FILE`-aware) — the same lookup `seed_users` uses,
    # so `cp .env.example .env && make demo-init && make demo-inject ...` needs no export (E20).
    password = read_env_value(TRAINEE_PASSWORD_ENV) or ""
    if not password:
        print(
            f"error: {TRAINEE_PASSWORD_ENV} is unset or empty (see .env.example; the trainee logs "
            "in exactly like a browser would)",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(
            run_injection(
                api_base_url=args.api,
                session_id=args.session,
                turns=turns,
                wait_caller=args.wait_caller,
                password=password,
            )
        )
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - process entry
    # E20-I: the LiveKit SDK's native (Rust/tokio) runtime panics while CPython finalises the
    # module after the room has already been disconnected ("panic in a function that cannot
    # unwind" -> SIGABRT, exit 134) — every turn had completed, but the exit status lied. Flush and
    # leave without interpreter finalisation so the exit code is the CLI's own.
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
