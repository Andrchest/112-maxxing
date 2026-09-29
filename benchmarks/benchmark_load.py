#!/usr/bin/env python
"""Load benchmark: N concurrent ДДС trainees + one instructor against a real backend (I7 E48).

ТЗ ¶159 (REQ-2137) «Время отклика интерфейса не более 2 секунд при нагрузке до 100 пользователей»
and the owner's item 8 («≥ 20 одновременных сессий обучаемых + инструктор, без GPU»).

What one run does, all of it over the product's own HTTP API and WebSocket:

1. **Setup** (as the seeded ADMIN, then as a fresh INSTRUCTOR): creates one instructor and N
   trainee accounts (`createUser`), finds the committed memo-mode example `street-rubbish-fire`,
   creates ONE lesson (`createLesson`, `SINGLE_ROLE`, `GENERATED_CARD`, `MEMO_STATUSES`) with
   `--cards-per-trainee` cards per trainee, every card arriving at lesson offset 0 and bound to
   its trainee (`PlanEntry.participants`), and starts it (`startLesson`) — N×K sessions `ACTIVE`
   at once, each ticked by the backend's D7 runner.
2. **Trainees** (N concurrent virtual users, logins spread over `--ramp-s`): log in, read
   `getCurrentUser`, poll «Список происшествий» (`listMyIncidents`) every `--incident-poll-ms`
   like the UI does, and for each of their cards: read the snapshot, open the session's
   WebSocket (`resume` from 0), read the legs and notifications, then work the card as the memo
   console does — Служба 101's leg `open` → `ACCEPTED` (with an order number and a comment) →
   `RESPONSE_STARTED` → `ARRIVED` → `WORKING` → `COMPLETED` (comment), every other notified
   service `open` → `NOT_ACCEPTED` (the mandatory comment), the «ЧС/ЧП» marks, then
   `closeDdsIncident` — with a seeded think time of `--think-ms` between actions and a legs
   re-read after each status (the console's refetch on the WebSocket event).
3. **Instructor** (one virtual user): polls the lesson board (`getLesson`) and the live overview
   (`getInstructorSessionOverview`) of one card at a time, round-robin, every
   `--instructor-poll-ms` (the board's own 3 s), with the WebSocket of the first card open.

Measured, per N: every request's wall time (p50/p95/p99/max per operation), its status (every
non-2xx and every transport error is counted), response bytes, WebSocket event delivery latency
(client receive time − the event's server `timestamp_utc`, one host clock), the WebSocket connect
time (handshake → `resume_complete`), and the backend process's RSS and CPU (the captured
`uvicorn` PID, `/proc` only). `--trainees 20 50 100` runs the three sizes one after the other in
one stack, each with its own accounts and lesson; a run's lesson is aborted at its end so a card
left open cannot tick into the next run.

`--own-stack` (the default without `--base-url`) starts the scratch stack of `_load_stack.py`
(compose project `sim112load`, loopback ports of its own, fake providers, no GPU) and tears it
down with `down -v` at the end. `--base-url` drives an already-running backend instead, with the
ADMIN credentials from `$BENCH_LOAD_ADMIN_USER`/`$BENCH_LOAD_ADMIN_PASSWORD` (never a flag, never
logged) and `--backend-pid` for the RSS/CPU samplers. A backend that cannot be reached, or a stack
that cannot start, is an honest `NOT_RUN` with the reason (`_common.write_result`).

Not measured, by design: voice (the fake transport carries no audio), the browser's own render
time, and anything across a real network — the clients run on the same host as the backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import secrets
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from _common import Envelope, ProcCpuSampler, aggregate, finish, not_run, parse_common_args
from _load_stack import (
    DEFAULT_API_PORT,
    DEFAULT_PG_PORT,
    DEFAULT_PROJECT,
    DEFAULT_REDIS_PORT,
    OwnStack,
    StackConfig,
    StackError,
    read_rss_mb,
)

BENCHMARK = "load"
#: ТЗ ¶159 (REQ-2137): interface response time no more than 2 s at up to 100 users.
TARGET_P95_MS = 2000.0
SCENARIO_SLUG = "street-rubbish-fire"
#: The memo walk of the leg the trainee takes (HLD 70 §70.4.2, `SERVICE_RESPONSE_TRANSITIONS`).
PRIMARY_WALK = ("ACCEPTED", "RESPONSE_STARTED", "ARRIVED", "WORKING", "COMPLETED")
PRIMARY_SERVICE = "FIRE_RESCUE"
API = "/api/v1"
WS_CONNECT_TIMEOUT_S = 30.0
KEEPALIVE_EXPIRY_S = 4.0
#: `createLesson`/`startLesson` create and start every card in one request (70 §70.3); with a
#: hundred cards that is far longer than an interactive request, and it is setup, not the measure.
SETUP_TIMEOUT_S = 600.0

ADMIN_USER_ENV = "BENCH_LOAD_ADMIN_USER"
ADMIN_PASSWORD_ENV = "BENCH_LOAD_ADMIN_PASSWORD"


def _extra(parser: Any) -> None:
    parser.add_argument(
        "--trainees",
        type=int,
        nargs="+",
        default=[20],
        metavar="N",
        help="concurrent trainees per run; several values run one after another (20 50 100)",
    )
    parser.add_argument("--cards-per-trainee", type=int, default=2)
    parser.add_argument(
        "--think-ms",
        type=int,
        nargs=2,
        default=[1000, 3000],
        metavar=("MIN", "MAX"),
        help="a trainee's seeded think time between two actions (uniform)",
    )
    parser.add_argument("--ramp-s", type=float, default=10.0, help="logins spread over this long")
    parser.add_argument("--incident-poll-ms", type=int, default=3000, help="0 disables it")
    parser.add_argument("--instructor-poll-ms", type=int, default=3000)
    parser.add_argument("--request-timeout-s", type=float, default=30.0)
    parser.add_argument(
        "--base-url",
        default=None,
        help="drive this running backend instead of starting the scratch stack",
    )
    parser.add_argument("--backend-pid", type=int, default=None, help="with --base-url: sample it")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="the scratch compose project")
    parser.add_argument("--pg-port", type=int, default=DEFAULT_PG_PORT)
    parser.add_argument("--redis-port", type=int, default=DEFAULT_REDIS_PORT)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--tick-ms", type=int, default=500, help="the backend's SIM_SIM_TICK_MS")
    parser.add_argument(
        "--keep-stack", action="store_true", help="debug only: leave the scratch stack running"
    )


# ---------------------------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------------------------


@dataclass
class Recorder:
    """Every request and every WebSocket event of one run, as raw samples."""

    trainees: int
    started: float = field(default_factory=time.perf_counter)
    samples: list[dict[str, Any]] = field(default_factory=list)

    def request(
        self, actor: str, op: str, ms: float, status: int, nbytes: int, error: str | None = None
    ) -> None:
        self.samples.append(
            {
                "trainees": self.trainees,
                "kind": "http",
                "actor": actor,
                "op": op,
                "ms": round(ms, 3),
                "status": status,
                "ok": 200 <= status < 300,
                "bytes": nbytes,
                "t_s": round(time.perf_counter() - self.started, 3),
                "error": error,
            }
        )

    def ws(self, actor: str, op: str, ms: float, ok: bool = True, error: str | None = None) -> None:
        self.samples.append(
            {
                "trainees": self.trainees,
                "kind": "ws",
                "actor": actor,
                "op": op,
                "ms": round(ms, 3),
                "status": 0,
                "ok": ok,
                "bytes": 0,
                "t_s": round(time.perf_counter() - self.started, 3),
                "error": error,
            }
        )


def summarize(samples: Sequence[dict[str, Any]], duration_s: float) -> dict[str, Any]:
    """Per-operation percentiles, error counts and the ¶159 verdict over one run's samples.

    `interactive` is every trainee and instructor HTTP request — what a person at a screen waits
    for; `setup` requests (accounts, lesson) are reported per operation but kept out of it.
    """
    http = [sample for sample in samples if sample["kind"] == "http"]
    by_op: dict[str, dict[str, Any]] = {}
    for op in sorted({sample["op"] for sample in http}):
        rows = [sample for sample in http if sample["op"] == op]
        ok_ms = [sample["ms"] for sample in rows if sample["ok"]]
        entry = aggregate(ok_ms)
        entry["requests"] = len(rows)
        entry["errors"] = sum(1 for sample in rows if not sample["ok"])
        entry["mean_bytes"] = sum(sample["bytes"] for sample in rows) / len(rows) if rows else None
        by_op[op] = entry
    interactive = [sample for sample in http if sample["actor"] in ("trainee", "instructor")]
    interactive_ms = [sample["ms"] for sample in interactive]
    over = sum(1 for value in interactive_ms if value > TARGET_P95_MS)
    errors = sum(1 for sample in http if not sample["ok"])
    interactive_errors = sum(1 for sample in interactive if not sample["ok"])
    ws_events = [sample["ms"] for sample in samples if sample["op"] == "ws_event"]
    ws_connect = [
        sample["ms"] for sample in samples if sample["op"] == "ws_connect" and sample["ok"]
    ]
    ws_errors = sum(1 for sample in samples if sample["kind"] == "ws" and not sample["ok"])
    interactive_agg = aggregate(interactive_ms)
    p95 = interactive_agg["p95"]
    return {
        "duration_s": round(duration_s, 3),
        "requests": len(http),
        "errors": errors,
        "error_rate": errors / len(http) if http else None,
        "throughput_rps": len(http) / duration_s if duration_s > 0 else None,
        "interactive_ms": interactive_agg,
        "interactive_over_target": over,
        "interactive_over_target_rate": over / len(interactive_ms) if interactive_ms else None,
        "target_p95_ms": TARGET_P95_MS,
        "interactive_errors": interactive_errors,
        "meets_target": (
            None if p95 is None else bool(p95 <= TARGET_P95_MS and interactive_errors == 0)
        ),
        "ops": by_op,
        "ws_event_latency_ms": aggregate(ws_events),
        "ws_connect_ms": aggregate(ws_connect),
        "ws_errors": ws_errors,
    }


# ---------------------------------------------------------------------------------------------
# Pure pieces: the trainee's plan, the WebSocket latency
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One status the trainee sets on one leg (after opening it when it is still `ADDED`)."""

    assignment_id: str
    service_type: str
    status: str
    body: dict[str, Any]


def leg_steps(legs: Sequence[dict[str, Any]]) -> list[Step]:
    """The memo console walk over `listDdsLegs`: the primary leg all the way to `COMPLETED`,
    every other leg of the trainee's declined with the mandatory comment.

    Only legs the caller plays (`is_mine`) are touched; a leg already past `ADDED`/`RECEIVED` is
    left alone (the plan is for a fresh card). The primary leg is Служба 101 when it is notified,
    otherwise the first leg offering `accept`.
    """
    mine = [
        leg
        for leg in legs
        if leg.get("is_mine") and leg.get("response_status") in ("ADDED", "RECEIVED")
    ]
    if not mine:
        return []
    primary = next(
        (leg for leg in mine if leg.get("service_type") == PRIMARY_SERVICE),
        None,
    ) or next(
        (
            leg
            for leg in mine
            if any(action.get("action_id") == "accept" for action in leg["available_actions"])
        ),
        mine[0],
    )
    steps: list[Step] = []
    for status in PRIMARY_WALK:
        body: dict[str, Any] = {"status": status}
        if status == "ACCEPTED":
            body["order_number"] = "Н-001"
            body["comment_ru"] = "Принято, расчёт выезжает"
        if status == "COMPLETED":
            body["comment_ru"] = "Возгорание ликвидировано"
        steps.append(
            Step(str(primary["assignment_id"]), str(primary["service_type"]), status, body)
        )
    for leg in mine:
        if leg is primary:
            continue
        steps.append(
            Step(
                str(leg["assignment_id"]),
                str(leg["service_type"]),
                "NOT_ACCEPTED",
                {"status": "NOT_ACCEPTED", "comment_ru": "Не наша компетенция"},
            )
        )
    return steps


def ws_event_latency_ms(frame: dict[str, Any], received_at: datetime) -> float | None:
    """`received_at − timestamp_utc` of an `event` frame in ms; `None` for any other frame.

    `timestamp_utc` is stamped by the event store when the row is written, before the commit and
    the Redis publish, so this is commit + publish + fan-out + the socket write — "server event →
    client". Both ends read the same host clock.
    """
    if frame.get("type") != "event":
        return None
    raw = frame.get("timestamp_utc")
    if not isinstance(raw, str):
        return None
    stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    return (received_at - stamped).total_seconds() * 1000.0


def think_s(rng: random.Random, think_ms: Sequence[int]) -> float:
    low, high = sorted(think_ms)
    return rng.uniform(low, high) / 1000.0


# ---------------------------------------------------------------------------------------------
# The HTTP/WebSocket clients
# ---------------------------------------------------------------------------------------------


class ApiUser:
    """One virtual user: its own `httpx.AsyncClient` (a browser's own connection pool)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        recorder: Recorder,
        actor: str,
    ) -> None:
        self.client = client
        self.recorder = recorder
        self.actor = actor
        self.token: str | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def call(
        self,
        op: str,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: Any = None,
        request_timeout_s: float | None = None,
    ) -> httpx.Response | None:
        """Time one request; every outcome, including a transport error, becomes a sample."""
        started = time.perf_counter()
        extra: dict[str, Any] = {} if request_timeout_s is None else {"timeout": request_timeout_s}
        try:
            response = await self.client.request(
                method, path, headers=self.headers, json=json_body, params=params, **extra
            )
        except httpx.HTTPError as exc:
            self.recorder.request(
                self.actor, op, (time.perf_counter() - started) * 1000.0, 0, 0, type(exc).__name__
            )
            return None
        elapsed = (time.perf_counter() - started) * 1000.0
        error = None if response.is_success else _problem_code(response)
        self.recorder.request(
            self.actor, op, elapsed, response.status_code, len(response.content), error
        )
        return response

    async def login(self, username: str, password: str) -> bool:
        response = await self.call(
            "login",
            "POST",
            f"{API}/auth/login",
            json_body={"username": username, "password": password},
        )
        if response is None or not response.is_success:
            return False
        self.token = str(response.json()["access_token"])
        return True


def _problem_code(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP_{response.status_code}"
    if isinstance(body, dict) and isinstance(body.get("code"), str):
        return str(body["code"])
    return f"HTTP_{response.status_code}"


#: `connect(url) -> socket` — `websockets.asyncio.client.connect` in a real run, a fake in tests.
WsConnect = Callable[[str], Awaitable[Any]]


async def _real_ws_connect(url: str) -> Any:
    from websockets.asyncio.client import connect

    return await connect(url, open_timeout=WS_CONNECT_TIMEOUT_S, max_size=None)


class WsWatcher:
    """One session's WebSocket: `resume` from 0, then every live event's delivery latency."""

    def __init__(
        self,
        connect: WsConnect,
        url: str,
        recorder: Recorder,
        actor: str,
    ) -> None:
        self._connect = connect
        self._url = url
        self._recorder = recorder
        self._actor = actor
        self._socket: Any = None
        self._task: asyncio.Task[None] | None = None
        self.live_events = 0

    async def start(self) -> bool:
        started = time.perf_counter()
        try:
            self._socket = await self._connect(self._url)
            await self._socket.send(json.dumps({"type": "resume", "after_seq_no": 0}))
            while True:
                frame = json.loads(
                    await asyncio.wait_for(self._socket.recv(), timeout=WS_CONNECT_TIMEOUT_S)
                )
                if frame.get("type") == "resume_complete":
                    break
                if frame.get("type") == "error":
                    raise RuntimeError(str(frame.get("code")))
        except Exception as exc:
            self._recorder.ws(
                self._actor,
                "ws_connect",
                (time.perf_counter() - started) * 1000.0,
                ok=False,
                error=type(exc).__name__,
            )
            await self.stop()
            return False
        self._recorder.ws(self._actor, "ws_connect", (time.perf_counter() - started) * 1000.0)
        self._task = asyncio.create_task(self._pump(), name="ws-watcher")
        return True

    async def _pump(self) -> None:
        try:
            while True:
                raw = await self._socket.recv()
                received_at = datetime.now(UTC)
                frame = json.loads(raw)
                latency = ws_event_latency_ms(frame, received_at)
                if latency is not None:
                    self.live_events += 1
                    self._recorder.ws(self._actor, "ws_event", latency)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not _is_normal_close(exc):
                self._recorder.ws(self._actor, "ws_drop", 0.0, ok=False, error=type(exc).__name__)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        if self._socket is not None:
            # Closing a socket the server already dropped is not a finding.
            with contextlib.suppress(Exception):
                await self._socket.close()
            self._socket = None


def _is_normal_close(exc: BaseException) -> bool:
    code = getattr(getattr(exc, "rcvd", None), "code", None)
    return code in (1000, 1001)


# ---------------------------------------------------------------------------------------------
# Resource sampling
# ---------------------------------------------------------------------------------------------


class RssSampler:
    """`VmRSS` of one captured PID once a second on a thread (`/proc`, no psutil)."""

    def __init__(self, pid: int, interval_s: float = 1.0) -> None:
        self._pid = pid
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.samples: list[float] = []

    def start(self) -> None:
        if read_rss_mb(self._pid) is None:
            return
        self._thread = threading.Thread(target=self._loop, name="rss-sampler", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            value = read_rss_mb(self._pid)
            if value is not None:
                self.samples.append(value)
            self._stop.wait(self._interval_s)

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        return aggregate(self.samples)


# ---------------------------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------------------------


@dataclass
class RunPlan:
    trainees: int
    cards_per_trainee: int
    think_ms: tuple[int, int]
    ramp_s: float
    incident_poll_ms: int
    instructor_poll_ms: int
    seed: int
    request_timeout_s: float


@dataclass
class RunOutcome:
    recorder: Recorder
    duration_s: float
    cards_planned: int
    cards_closed: int
    sessions_completed: int | None
    setup_error: str | None = None
    notes: list[str] = field(default_factory=list)


ClientFactory = Callable[[], httpx.AsyncClient]


async def run_once(
    plan: RunPlan,
    *,
    make_client: ClientFactory,
    ws_base: str,
    ws_connect: WsConnect,
    admin_username: str,
    admin_password: str,
) -> RunOutcome:
    """Setup, N trainees + one instructor, teardown of the lesson. Never raises for a refusal:
    a setup failure is `setup_error`, every request failure is a sample."""
    recorder = Recorder(trainees=plan.trainees)
    rng = random.Random(plan.seed * 1_000_003 + plan.trainees)
    run_tag = secrets.token_hex(3)
    password = secrets.token_urlsafe(18)
    clients: list[httpx.AsyncClient] = []

    def new_user(actor: str) -> ApiUser:
        client = make_client()
        clients.append(client)
        return ApiUser(client, recorder, actor)

    try:
        admin = new_user("setup")
        if not await admin.login(admin_username, admin_password):
            return _setup_failed(recorder, plan, "the ADMIN could not log in")
        instructor_name = f"load{run_tag}i"
        created = await _create_user(admin, instructor_name, "INSTRUCTOR", password)
        if created is None:
            return _setup_failed(recorder, plan, "createUser(INSTRUCTOR) was refused")
        trainee_names = [f"load{run_tag}t{index:03d}" for index in range(plan.trainees)]
        trainee_ids: list[str] = []
        for chunk in _chunks(trainee_names, 8):
            ids = await asyncio.gather(
                *(_create_user(admin, name, "TRAINEE", password) for name in chunk)
            )
            if any(user_id is None for user_id in ids):
                return _setup_failed(recorder, plan, "createUser(TRAINEE) was refused")
            trainee_ids.extend(str(user_id) for user_id in ids)

        setup = new_user("setup")
        if not await setup.login(instructor_name, password):
            return _setup_failed(recorder, plan, "the new INSTRUCTOR could not log in")
        version_id = await _scenario_version_id(setup, SCENARIO_SLUG)
        if version_id is None:
            return _setup_failed(recorder, plan, f"scenario {SCENARIO_SLUG!r} is not imported")
        lesson_body = lesson_request(trainee_ids, version_id, plan.cards_per_trainee)
        response = await setup.call(
            "create_lesson",
            "POST",
            f"{API}/lessons",
            json_body=lesson_body,
            request_timeout_s=SETUP_TIMEOUT_S,
        )
        if response is None or response.status_code != 201:
            return _setup_failed(recorder, plan, "createLesson was refused")
        lesson_id = str(response.json()["lesson_id"])
        response = await setup.call(
            "start_lesson",
            "POST",
            f"{API}/lessons/{lesson_id}/start",
            request_timeout_s=SETUP_TIMEOUT_S,
        )
        if response is None or not response.is_success:
            return _setup_failed(recorder, plan, "startLesson was refused")
        session_ids = [str(item["session_id"]) for item in response.json()["sessions"]]

        recorder.started = time.perf_counter()
        stop = asyncio.Event()
        instructor = new_user("instructor")
        instructor_task = asyncio.create_task(
            _instructor(
                instructor,
                instructor_name,
                password,
                lesson_id,
                session_ids,
                plan,
                stop,
                ws_base,
                ws_connect,
            )
        )
        trainee_tasks = [
            asyncio.create_task(
                _trainee(
                    new_user("trainee"),
                    name,
                    password,
                    plan,
                    random.Random(rng.random()),
                    delay_s=plan.ramp_s * index / max(1, plan.trainees),
                    ws_base=ws_base,
                    ws_connect=ws_connect,
                )
            )
            for index, name in enumerate(trainee_names)
        ]
        closed_counts = await asyncio.gather(*trainee_tasks)
        stop.set()
        await instructor_task
        duration = time.perf_counter() - recorder.started

        # Outside the measured window: what the lesson says happened, then stop it for good.
        final = await setup.call("lesson_final", "GET", f"{API}/lessons/{lesson_id}")
        completed = None
        lesson_state = None
        if final is not None and final.is_success:
            lesson_state = final.json()["state"]
            completed = sum(1 for item in final.json()["sessions"] if item["state"] == "COMPLETED")
        if lesson_state not in ("COMPLETED", "ABORTED"):
            await setup.call(
                "lesson_abort",
                "POST",
                f"{API}/lessons/{lesson_id}/abort",
                json_body={"reason": "Нагрузочный прогон окончен"},
            )
        return RunOutcome(
            recorder=recorder,
            duration_s=duration,
            cards_planned=plan.trainees * plan.cards_per_trainee,
            cards_closed=sum(closed_counts),
            sessions_completed=completed,
        )
    finally:
        for client in clients:
            await client.aclose()


def _setup_failed(recorder: Recorder, plan: RunPlan, reason: str) -> RunOutcome:
    return RunOutcome(
        recorder=recorder,
        duration_s=0.0,
        cards_planned=plan.trainees * plan.cards_per_trainee,
        cards_closed=0,
        sessions_completed=None,
        setup_error=reason,
    )


def _chunks(items: Sequence[str], size: int) -> list[Sequence[str]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def lesson_request(
    trainee_ids: Sequence[str], version_id: str, cards_per_trainee: int
) -> dict[str, Any]:
    """`createLesson`: one card per trainee per round, every card due at lesson offset 0."""
    plan: list[dict[str, Any]] = []
    for _round in range(cards_per_trainee):
        for trainee_id in trainee_ids:
            plan.append(
                {
                    "position": len(plan) + 1,
                    "scenario_version_id": version_id,
                    "arrival": {"kind": "AT_OFFSET", "offset_ms": 0},
                    "participants": [trainee_id],
                }
            )
    return {
        "title_ru": "Нагрузочный прогон",
        "session_mode": "SINGLE_ROLE",
        "participants": [
            {"user_id": trainee_id, "assigned_role_type": "DDS"} for trainee_id in trainee_ids
        ],
        "variants": {"card_source": "GENERATED_CARD", "dds_mode": "MEMO_STATUSES"},
        "scenario_plan": plan,
    }


async def _create_user(admin: ApiUser, username: str, role: str, password: str) -> str | None:
    response = await admin.call(
        "create_user",
        "POST",
        f"{API}/admin/users",
        json_body={
            "username": username,
            "display_name_ru": "Нагрузочный тест",
            "user_role": role,
            "password": password,
        },
    )
    if response is None or response.status_code != 201:
        return None
    return str(response.json()["id"])


async def _scenario_version_id(user: ApiUser, slug: str) -> str | None:
    response = await user.call("list_scenarios", "GET", f"{API}/scenarios", params={"limit": 200})
    if response is None or not response.is_success:
        return None
    scenario = next((item for item in response.json()["items"] if item["slug"] == slug), None)
    if scenario is None:
        return None
    response = await user.call(
        "list_scenario_versions", "GET", f"{API}/scenarios/{scenario['scenario_id']}/versions"
    )
    if response is None or not response.is_success or not response.json()["items"]:
        return None
    return str(response.json()["items"][0]["id"])


def _ws_url(ws_base: str, session_id: str, token: str | None) -> str:
    return f"{ws_base}{API}/ws/sessions/{session_id}?token={token or ''}"


async def _trainee(
    user: ApiUser,
    username: str,
    password: str,
    plan: RunPlan,
    rng: random.Random,
    *,
    delay_s: float,
    ws_base: str,
    ws_connect: WsConnect,
) -> int:
    """One trainee's whole lesson; returns how many of their cards were closed."""
    await asyncio.sleep(delay_s)
    if not await user.login(username, password):
        return 0
    await user.call("me", "GET", f"{API}/auth/me")
    poller = (
        asyncio.create_task(_poll_incidents(user, plan.incident_poll_ms / 1000.0))
        if plan.incident_poll_ms > 0
        else None
    )
    closed = 0
    try:
        response = await user.call(
            "list_incidents", "GET", f"{API}/incidents", params={"role_type": "DDS"}
        )
        if response is None or not response.is_success:
            return 0
        session_ids = [
            str(item["session_id"])
            for item in sorted(response.json()["items"], key=lambda item: item["display_number"])
            if item["session_state"] == "ACTIVE"
        ]
        for session_id in session_ids:
            if await _work_card(user, session_id, plan, rng, ws_base, ws_connect):
                closed += 1
    finally:
        if poller is not None:
            poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poller
    return closed


async def _poll_incidents(user: ApiUser, interval_s: float) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await user.call("list_incidents", "GET", f"{API}/incidents", params={"role_type": "DDS"})


async def _work_card(
    user: ApiUser,
    session_id: str,
    plan: RunPlan,
    rng: random.Random,
    ws_base: str,
    ws_connect: WsConnect,
) -> bool:
    base = f"{API}/sessions/{session_id}"
    await user.call("snapshot", "GET", f"{base}/snapshot")
    watcher = WsWatcher(
        ws_connect, _ws_url(ws_base, session_id, user.token), user.recorder, "trainee"
    )
    await watcher.start()
    try:
        response = await user.call("legs", "GET", f"{base}/dds/legs")
        await user.call("notifications", "GET", f"{base}/dds/notifications")
        if response is None or not response.is_success:
            return False
        opened: set[str] = set()
        for step in leg_steps(response.json()):
            await asyncio.sleep(think_s(rng, plan.think_ms))
            if step.assignment_id not in opened:
                opened.add(step.assignment_id)
                await user.call("leg_open", "POST", f"{base}/dds/legs/{step.assignment_id}/open")
            await user.call(
                "leg_status",
                "POST",
                f"{base}/dds/legs/{step.assignment_id}/status",
                json_body=step.body,
            )
            await user.call("legs", "GET", f"{base}/dds/legs")
        await asyncio.sleep(think_s(rng, plan.think_ms))
        await user.call(
            "card_marks", "POST", f"{base}/dds/card-marks", json_body={"chs": False, "chp": True}
        )
        await asyncio.sleep(think_s(rng, plan.think_ms))
        response = await user.call(
            "close",
            "POST",
            f"{base}/dds/close",
            json_body={"closure_reason": "RESOLVED", "comment_ru": "Работы завершены"},
        )
        closed = response is not None and response.is_success
        await user.call("snapshot", "GET", f"{base}/snapshot")
        return closed
    finally:
        await watcher.stop()


async def _instructor(
    user: ApiUser,
    username: str,
    password: str,
    lesson_id: str,
    session_ids: Sequence[str],
    plan: RunPlan,
    stop: asyncio.Event,
    ws_base: str,
    ws_connect: WsConnect,
) -> None:
    if not await user.login(username, password):
        return
    watcher: WsWatcher | None = None
    if session_ids:
        watcher = WsWatcher(
            ws_connect, _ws_url(ws_base, session_ids[0], user.token), user.recorder, "instructor"
        )
        await watcher.start()
    index = 0
    try:
        while not stop.is_set():
            await user.call("lesson_board", "GET", f"{API}/lessons/{lesson_id}")
            if session_ids:
                session_id = session_ids[index % len(session_ids)]
                index += 1
                await user.call(
                    "instructor_overview", "GET", f"{API}/instructor/sessions/{session_id}/overview"
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=plan.instructor_poll_ms / 1000.0)
    finally:
        if watcher is not None:
            await watcher.stop()


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------


async def _probe(make_client: ClientFactory) -> str | None:
    client = make_client()
    try:
        response = await client.get(f"{API}/health/live")
    except httpx.HTTPError as exc:
        return f"the backend is not reachable: {type(exc).__name__}"
    finally:
        await client.aclose()
    if response.status_code != 200:
        return f"the backend answered /health/live with {response.status_code}"
    return None


def _host_facts() -> dict[str, Any]:
    facts: dict[str, Any] = {"cpu_count": os.cpu_count()}
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    facts["cpu_model"] = line.split(":", 1)[1].strip()
                    break
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    facts["mem_total_gb"] = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:
        pass
    return facts


async def drive(
    args: Any,
    envelope: Envelope,
    *,
    base_url: str,
    admin_username: str,
    admin_password: str,
    backend_pid: int | None,
    ws_connect: WsConnect = _real_ws_connect,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Run every `--trainees` size against `base_url`; fills `envelope` (samples, aggregates)."""

    def make_client() -> httpx.AsyncClient:
        # An idle keep-alive connection is dropped client-side before uvicorn's own 5 s
        # `timeout_keep_alive` closes it, as a browser does: otherwise a request can race the
        # server's close and fail with a `ReadError` that says nothing about the backend.
        return httpx.AsyncClient(
            base_url=base_url,
            timeout=args.request_timeout_s,
            transport=transport,
            limits=httpx.Limits(keepalive_expiry=KEEPALIVE_EXPIRY_S),
        )

    refusal = await _probe(make_client)
    if refusal is not None:
        envelope.status = "NOT_RUN"
        envelope.reason = refusal
        return
    ws_base = "ws" + base_url[len("http") :] if base_url.startswith("http") else base_url
    by_trainees: dict[str, Any] = {}
    problems: list[str] = []
    for trainees in args.trainees:
        plan = RunPlan(
            trainees=trainees,
            cards_per_trainee=args.cards_per_trainee,
            think_ms=(args.think_ms[0], args.think_ms[1]),
            ramp_s=args.ramp_s,
            incident_poll_ms=args.incident_poll_ms,
            instructor_poll_ms=args.instructor_poll_ms,
            seed=args.seed,
            request_timeout_s=args.request_timeout_s,
        )
        cpu = ProcCpuSampler(backend_pid, interval_ms=1000) if backend_pid else None
        rss = RssSampler(backend_pid) if backend_pid else None
        if cpu is not None:
            cpu.start()
        if rss is not None:
            rss.start()
        outcome = await run_once(
            plan,
            make_client=make_client,
            ws_base=ws_base,
            ws_connect=ws_connect,
            admin_username=admin_username,
            admin_password=admin_password,
        )
        cpu_agg = cpu.stop() if cpu is not None else None
        rss_agg = rss.stop() if rss is not None else None
        envelope.samples.extend(outcome.recorder.samples)
        if outcome.setup_error is not None:
            problems.append(f"N={trainees}: {outcome.setup_error}")
            continue
        summary = summarize(outcome.recorder.samples, outcome.duration_s)
        summary.update(
            {
                "trainees": trainees,
                "cards_planned": outcome.cards_planned,
                "cards_closed": outcome.cards_closed,
                "sessions_completed": outcome.sessions_completed,
                "backend_cpu_percent": cpu_agg,
                "backend_rss_mb": rss_agg,
            }
        )
        if (
            summary["errors"]
            or summary["ws_errors"]
            or outcome.cards_closed != outcome.cards_planned
        ):
            problems.append(
                f"N={trainees}: {summary['errors']} failed request(s), "
                f"{summary['ws_errors']} failed WebSocket connect(s)/drop(s), "
                f"{outcome.cards_closed}/{outcome.cards_planned} card(s) closed"
            )
        by_trainees[str(trainees)] = summary
    if by_trainees:
        envelope.aggregates = {"by_trainees": by_trainees}
    if not envelope.samples:
        envelope.status = "NOT_RUN"
        envelope.reason = "; ".join(problems) or "no request was made"
        envelope.aggregates = {}
        return
    if not by_trainees:
        envelope.status = "FAILED"
        envelope.reason = "; ".join(problems)
        return
    envelope.status = "PARTIAL" if problems else "OK"
    if problems:
        envelope.reason = "; ".join(problems)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_common_args(
        BENCHMARK,
        argv,
        extra=_extra,
        description="N concurrent ДДС trainees + one instructor over HTTP+WS (ТЗ ¶159)",
    )
    config = {
        "trainees": list(args.trainees),
        "cards_per_trainee": args.cards_per_trainee,
        "think_ms": list(args.think_ms),
        "ramp_s": args.ramp_s,
        "incident_poll_ms": args.incident_poll_ms,
        "instructor_poll_ms": args.instructor_poll_ms,
        "request_timeout_s": args.request_timeout_s,
        "scenario": SCENARIO_SLUG,
        "stack": "external" if args.base_url else "own",
        "tick_ms": args.tick_ms,
        "seed": args.seed,
        "tag": args.tag,
        "host": _host_facts(),
    }
    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    envelope.note("fake voice/LLM providers; no GPU; clients and backend on one host")
    envelope.note("ws_event: client receive time − event timestamp_utc (same host clock)")
    if args.base_url:
        admin_username = os.environ.get(ADMIN_USER_ENV, "")
        admin_password = os.environ.get(ADMIN_PASSWORD_ENV, "")
        if not admin_username or not admin_password:
            reason = f"--base-url needs ${ADMIN_USER_ENV} and ${ADMIN_PASSWORD_ENV}"
            return finish(not_run(BENCHMARK, args.profile, reason, config=config), args.out)
        asyncio.run(
            drive(
                args,
                envelope,
                base_url=args.base_url.rstrip("/"),
                admin_username=admin_username,
                admin_password=admin_password,
                backend_pid=args.backend_pid,
            )
        )
        return _finish(envelope, args)
    stack = OwnStack(
        StackConfig(
            project=args.project,
            pg_port=args.pg_port,
            redis_port=args.redis_port,
            api_port=args.api_port,
            tick_ms=args.tick_ms,
        ),
        keep=args.keep_stack,
    )
    try:
        with stack:
            config["compose_project"] = args.project
            asyncio.run(
                drive(
                    args,
                    envelope,
                    base_url=stack.base_url,
                    admin_username=stack.admin_username,
                    admin_password=stack.admin_password,
                    backend_pid=stack.backend_pid,
                )
            )
            if envelope.status in ("FAILED", "PARTIAL") and stack.backend_log is not None:
                envelope.note(f"backend log tail: {_log_tail(stack.backend_log)}")
    except StackError as exc:
        return finish(not_run(BENCHMARK, args.profile, str(exc), config=config), args.out)
    return _finish(envelope, args)


def _finish(envelope: Envelope, args: Any) -> int:
    if envelope.status == "NOT_RUN":
        envelope.samples = []
        envelope.aggregates = {}
    return finish(envelope, args.out)


def _log_tail(path: Any, lines: int = 5) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        return "(unreadable)"
    errors = [line for line in text if "ERROR" in line or "Traceback" in line]
    return " | ".join((errors or text)[-lines:])


if __name__ == "__main__":
    sys.exit(main())
