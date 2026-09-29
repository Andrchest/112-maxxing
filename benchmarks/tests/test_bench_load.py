"""`benchmark_load.py`, `benchmark_db.py` and `_load_stack.py` — the harness pieces, with fakes
(I7 E48).

Nothing here starts docker, a backend or a database, and nothing leaves the process: the HTTP side
of a whole run is an `httpx.MockTransport` fake of the dozen endpoints the virtual users call, the
WebSocket is an in-memory fake, and the only sockets touched are loopback probes that are refused
at once. **Shape and logic only** — no latency asserted here is a measurement.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import benchmark_db
import benchmark_load
import httpx
import pytest
from _load_stack import FORBIDDEN_PORTS, backend_env, compose_yaml, port_refusal, read_rss_mb
from test_bench_scripts import assert_csv_header_is_the_sample_keys, assert_envelope, read_result

# ---------------------------------------------------------------------------------------------
# Pure pieces
# ---------------------------------------------------------------------------------------------


def _leg(service: str, status: str = "ADDED", *, mine: bool = True) -> dict[str, Any]:
    return {
        "assignment_id": f"leg-{service}",
        "service_type": service,
        "response_status": status,
        "is_mine": mine,
        "available_actions": [{"action_id": "accept"}, {"action_id": "decline"}] if mine else [],
    }


def test_leg_steps_walks_the_primary_leg_and_declines_the_others_with_a_comment() -> None:
    legs = [_leg("TSODD"), _leg("FIRE_RESCUE"), _leg("OATI"), _leg("POLICE", mine=False)]

    steps = benchmark_load.leg_steps(legs)

    primary = [step for step in steps if step.service_type == "FIRE_RESCUE"]
    assert [step.status for step in primary] == list(benchmark_load.PRIMARY_WALK)
    assert primary[0].body["order_number"] and primary[0].body["comment_ru"]
    assert primary[-1].body["comment_ru"]
    declined = [step for step in steps if step.service_type != "FIRE_RESCUE"]
    assert {step.service_type for step in declined} == {"TSODD", "OATI"}
    assert all(step.status == "NOT_ACCEPTED" and step.body["comment_ru"] for step in declined)


def test_leg_steps_falls_back_to_the_first_acceptable_leg_and_skips_decided_ones() -> None:
    legs = [_leg("TSODD", "ACCEPTED"), _leg("OATI"), _leg("DDS_DISTRICT")]

    steps = benchmark_load.leg_steps(legs)

    assert steps[0].service_type == "OATI" and steps[0].status == "ACCEPTED"
    assert {step.service_type for step in steps} == {"OATI", "DDS_DISTRICT"}
    assert benchmark_load.leg_steps([_leg("TSODD", mine=False)]) == []


def test_ws_event_latency_is_receive_time_minus_the_server_stamp() -> None:
    stamped = datetime(2026, 9, 29, 10, 0, 0, tzinfo=UTC)
    frame = {"type": "event", "timestamp_utc": stamped.isoformat().replace("+00:00", "Z")}

    latency = benchmark_load.ws_event_latency_ms(frame, stamped + timedelta(milliseconds=42))

    assert latency == pytest.approx(42.0)
    heartbeat = {"type": "heartbeat", "server_time_utc": stamped.isoformat()}
    assert benchmark_load.ws_event_latency_ms(heartbeat, stamped) is None


def _sample(actor: str, op: str, ms: float, status: int = 200) -> dict[str, Any]:
    recorder = benchmark_load.Recorder(trainees=2)
    recorder.request(actor, op, ms, status, 10)
    return recorder.samples[0]


def test_summarize_keeps_setup_out_of_the_interactive_verdict() -> None:
    samples = [
        _sample("setup", "start_lesson", 40_000.0),
        _sample("trainee", "legs", 100.0),
        _sample("trainee", "legs", 300.0),
        _sample("instructor", "lesson_board", 200.0),
    ]

    summary = benchmark_load.summarize(samples, duration_s=2.0)

    assert summary["requests"] == 4 and summary["errors"] == 0
    assert summary["interactive_ms"]["n"] == 3 and summary["interactive_ms"]["max"] == 300.0
    assert summary["meets_target"] is True
    assert summary["ops"]["legs"]["requests"] == 2
    assert summary["throughput_rps"] == 2.0


def test_summarize_fails_the_target_on_an_interactive_error_or_a_slow_p95() -> None:
    failed = benchmark_load.summarize(
        [_sample("trainee", "legs", 10.0), _sample("trainee", "close", 5.0, status=409)], 1.0
    )
    assert failed["interactive_errors"] == 1 and failed["meets_target"] is False
    assert failed["ops"]["close"]["errors"] == 1 and failed["ops"]["close"]["n"] == 0

    slow = benchmark_load.summarize([_sample("trainee", "legs", 2500.0)], 1.0)
    assert slow["interactive_over_target"] == 1 and slow["meets_target"] is False


def test_the_lesson_binds_one_card_per_trainee_per_round_all_at_offset_zero() -> None:
    body = benchmark_load.lesson_request(["t1", "t2"], "v1", cards_per_trainee=2)

    plan = body["scenario_plan"]
    assert [entry["position"] for entry in plan] == [1, 2, 3, 4]
    assert [entry["participants"] for entry in plan] == [["t1"], ["t2"], ["t1"], ["t2"]]
    assert {entry["arrival"]["offset_ms"] for entry in plan} == {0}
    assert body["session_mode"] == "SINGLE_ROLE"
    assert body["variants"] == {"card_source": "GENERATED_CARD", "dds_mode": "MEMO_STATUSES"}
    assert {item["assigned_role_type"] for item in body["participants"]} == {"DDS"}


# ---------------------------------------------------------------------------------------------
# The scratch stack's pieces (nothing is started)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("port", [8000, 8001, 8011, 8012, 5000, 5180, 8120, 25432, 26379, 17880])
def test_the_demos_and_the_owners_ports_are_refused_without_binding(port: int) -> None:
    assert port in FORBIDDEN_PORTS
    refusal = port_refusal(port)
    assert refusal is not None and str(port) in refusal


def test_the_compose_file_binds_loopback_only_and_keeps_data_on_a_volume() -> None:
    text = compose_yaml(35432, 36379, "pw")

    assert '"127.0.0.1:35432:5432"' in text and '"127.0.0.1:36379:6379"' in text
    assert "pgdata:/var/lib/postgresql/data" in text
    assert "tmpfs" not in text
    assert "pg_isready -h 127.0.0.1" in text


def test_the_backend_env_fakes_every_provider_and_drops_foreign_sim_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SIM_DATABASE_URL", "postgresql+asyncpg://owner/demo")
    monkeypatch.setenv("SIM_SOMETHING_ELSE", "x")

    env = backend_env(
        database_url="postgresql+asyncpg://sim:pw@127.0.0.1:35432/sim_load",
        redis_url="redis://127.0.0.1:36379/0",
        api_port=18190,
        data_dir=tmp_path,
        jwt_secret="s" * 32,
        tick_ms=500,
    )

    assert env["SIM_DATABASE_URL"].endswith("127.0.0.1:35432/sim_load")
    assert "SIM_SOMETHING_ELSE" not in env
    assert env["SIM_ENV_FILE"] == ""
    for key in ("SIM_ASR_PROVIDER", "SIM_LLM_PROVIDER", "SIM_TTS_PROVIDER", "SIM_CALL_TRANSPORT"):
        assert env[key] == "fake"
    assert env["SIM_RUNNER_ENABLED"] == "true" and env["SIM_SIM_TICK_MS"] == "500"


def test_read_rss_reads_this_process_and_nothing_for_a_missing_pid() -> None:
    rss = read_rss_mb(os.getpid())
    assert rss is not None and rss > 0
    assert read_rss_mb(2**22 + 12345) is None


# ---------------------------------------------------------------------------------------------
# A whole run against a fake backend
# ---------------------------------------------------------------------------------------------


class FakeBackend:
    """The endpoints `benchmark_load` calls, in memory: accounts, one lesson, memo legs."""

    SERVICES = ("FIRE_RESCUE", "TSODD", "OATI")

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {
            "admin": {"id": str(uuid4()), "password": "admin-pw", "role": "ADMIN"}
        }
        self.tokens: dict[str, str] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lesson: dict[str, Any] | None = None
        self.closed: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == "/api/v1/health/live":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/auth/login":
            user = self.users.get(body["username"])
            if user is None or user["password"] != body["password"]:
                return httpx.Response(401, json={"code": "INVALID_CREDENTIALS"})
            token = uuid4().hex
            self.tokens[token] = body["username"]
            return httpx.Response(200, json={"access_token": token})
        username = self.tokens.get(request.headers.get("authorization", "")[len("Bearer ") :])
        if username is None:
            return httpx.Response(401, json={"code": "UNAUTHENTICATED"})
        return self._route(request.method, path, body, username)

    def _route(self, method: str, path: str, body: Any, username: str) -> httpx.Response:
        me = self.users[username]
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json={"id": me["id"]})
        if path == "/api/v1/admin/users":
            user_id = str(uuid4())
            self.users[body["username"]] = {
                "id": user_id,
                "password": body["password"],
                "role": body["user_role"],
            }
            return httpx.Response(201, json={"id": user_id})
        if path == "/api/v1/scenarios":
            items = [{"scenario_id": "s1", "slug": benchmark_load.SCENARIO_SLUG}]
            return httpx.Response(200, json={"items": items, "total": 1})
        if path == "/api/v1/scenarios/s1/versions":
            return httpx.Response(200, json={"items": [{"id": "v1"}], "total": 1})
        if path == "/api/v1/lessons" and method == "POST":
            self.lesson = {"lesson_id": "l1", "state": "CREATED", "plan": body["scenario_plan"]}
            return httpx.Response(201, json={"lesson_id": "l1"})
        if path == "/api/v1/lessons/l1/start":
            assert self.lesson is not None
            for entry in self.lesson["plan"]:
                session_id = str(uuid4())
                self.sessions[session_id] = {
                    "trainee": entry["participants"][0],
                    "number": entry["position"],
                    "legs": [_leg(service) for service in self.SERVICES],
                }
            self.lesson["state"] = "ACTIVE"
            return httpx.Response(200, json=self._lesson())
        if path == "/api/v1/lessons/l1":
            return httpx.Response(200, json=self._lesson())
        if path == "/api/v1/lessons/l1/abort":
            return httpx.Response(200, json=self._lesson())
        if path == "/api/v1/incidents":
            items = [
                {"session_id": sid, "display_number": s["number"], "session_state": "ACTIVE"}
                for sid, s in self.sessions.items()
                if s["trainee"] == me["id"] and sid not in self.closed
            ]
            return httpx.Response(200, json={"items": items, "total": len(items)})
        match = re.fullmatch(r"/api/v1/(?:instructor/)?sessions/([^/]+)(/.*)?", path)
        if match is None:
            return httpx.Response(404, json={"code": "NOT_FOUND"})
        session = self.sessions[match.group(1)]
        suffix = match.group(2) or ""
        if suffix in ("/snapshot", "/overview", "/dds/notifications"):
            return httpx.Response(200, json={"items": []})
        if suffix == "/dds/legs":
            return httpx.Response(200, json=session["legs"])
        if suffix.endswith("/open"):
            return httpx.Response(200, json={})
        if suffix.endswith("/status"):
            leg_id = suffix.split("/")[3]
            leg = next(item for item in session["legs"] if item["assignment_id"] == leg_id)
            leg["response_status"] = body["status"]
            return httpx.Response(200, json=leg)
        if suffix == "/dds/card-marks":
            return httpx.Response(200, json={})
        if suffix == "/dds/close":
            self.closed.add(match.group(1))
            session["state"] = "COMPLETED"
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"code": "NOT_FOUND"})

    def _lesson(self) -> dict[str, Any]:
        sessions = [
            {"session_id": sid, "state": "COMPLETED" if sid in self.closed else "ACTIVE"}
            for sid in self.sessions
        ]
        state = "COMPLETED" if sessions and len(self.closed) == len(sessions) else "ACTIVE"
        return {"lesson_id": "l1", "state": state, "sessions": sessions}


class FakeSocket:
    """`resume` → `resume_complete`, one live event, then silence until closed."""

    def __init__(self) -> None:
        self._frames: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))
        await self._frames.put(json.dumps({"type": "resume_complete", "replayed_count": 0}))
        stamp = datetime.now(UTC).isoformat()
        await self._frames.put(json.dumps({"type": "event", "timestamp_utc": stamp}))

    async def recv(self) -> str:
        return await self._frames.get()

    async def close(self) -> None:
        return None


def test_a_whole_run_against_a_fake_backend_closes_every_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = FakeBackend()
    sockets: list[FakeSocket] = []

    async def ws_connect(url: str) -> FakeSocket:
        assert "/api/v1/ws/sessions/" in url and "token=" in url
        sockets.append(FakeSocket())
        return sockets[-1]

    args = benchmark_load.parse_common_args(
        "load",
        [
            "--trainees",
            "3",
            "--cards-per-trainee",
            "2",
            "--think-ms",
            "0",
            "0",
            "--ramp-s",
            "0",
            "--incident-poll-ms",
            "5",
            "--instructor-poll-ms",
            "5",
        ],
        extra=benchmark_load._extra,
    )
    envelope = benchmark_load.Envelope(benchmark="load", status="OK", profile="DEV_3060TI")

    asyncio.run(
        benchmark_load.drive(
            args,
            envelope,
            base_url="http://fake",
            admin_username="admin",
            admin_password="admin-pw",
            backend_pid=os.getpid(),
            ws_connect=ws_connect,
            transport=httpx.MockTransport(backend.handler),
        )
    )

    assert envelope.status == "OK", envelope.reason
    summary = envelope.aggregates["by_trainees"]["3"]
    assert summary["cards_planned"] == 6 and summary["cards_closed"] == 6
    assert summary["sessions_completed"] == 6
    assert summary["errors"] == 0
    assert summary["ops"]["leg_status"]["requests"] == 6 * (len(benchmark_load.PRIMARY_WALK) + 2)
    assert summary["ops"]["close"]["requests"] == 6
    assert summary["ws_event_latency_ms"]["n"] >= 6
    assert summary["backend_rss_mb"]["n"] >= 1
    assert all(
        sent == [{"type": "resume", "after_seq_no": 0}] for sent in (s.sent for s in sockets)
    )

    out = tmp_path / "out"
    assert benchmark_load.finish(envelope, out) == 0
    payload, rows = read_result(out, "load")
    assert_envelope(payload, "load")
    assert_csv_header_is_the_sample_keys(payload, rows)


# ---------------------------------------------------------------------------------------------
# main(): the honest NOT_RUNs
# ---------------------------------------------------------------------------------------------


def test_an_external_backend_without_admin_credentials_is_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(benchmark_load.ADMIN_USER_ENV, raising=False)
    monkeypatch.delenv(benchmark_load.ADMIN_PASSWORD_ENV, raising=False)
    out = tmp_path / "out"

    assert benchmark_load.main(["--base-url", "http://127.0.0.1:1", "--out", str(out)]) == 0

    payload, rows = read_result(out, "load")
    assert_envelope(payload, "load", status="NOT_RUN")
    assert benchmark_load.ADMIN_PASSWORD_ENV in payload["reason"]
    assert rows == []


def test_an_unreachable_backend_is_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(benchmark_load.ADMIN_USER_ENV, "admin")
    monkeypatch.setenv(benchmark_load.ADMIN_PASSWORD_ENV, "not-a-real-password")
    out = tmp_path / "out"

    assert benchmark_load.main(["--base-url", "http://127.0.0.1:1", "--out", str(out)]) == 0

    payload, _rows = read_result(out, "load")
    assert_envelope(payload, "load", status="NOT_RUN")
    assert "not reachable" in payload["reason"]
    assert "not-a-real-password" not in json.dumps(payload)


def test_db_summary_states_the_rate_against_the_target() -> None:
    summary = benchmark_db.summarize([5.0, 7.0, 9.0, 11.0], errors=[], wall_s=0.02)

    assert summary["appends"] == 4 and summary["appends_per_s"] == pytest.approx(200.0)
    assert summary["meets_target"] is True
    assert summary["append_ms"]["n"] == 4 and summary["append_ms"]["max"] == 11.0
    assert (
        benchmark_db.summarize([5.0], errors=["TimeoutError"], wall_s=0.001)["meets_target"]
        is False
    )
    assert benchmark_db.summarize([5.0], errors=[], wall_s=1.0)["meets_target"] is False


def test_an_unreachable_database_is_not_run(tmp_path: Path) -> None:
    out = tmp_path / "out"
    url = "postgresql+asyncpg://sim:x@127.0.0.1:1/none"

    argv = ["--database-url", url, "--writers", "1", "--appends", "1", "--out", str(out)]
    assert benchmark_db.main(argv) == 0

    payload, rows = read_result(out, "db")
    assert_envelope(payload, "db", status="NOT_RUN")
    assert rows == []
