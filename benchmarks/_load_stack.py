"""The load benchmarks' own scratch stack (I7 E48): PostgreSQL + Redis in a compose project of
their own, the schema migrated, the seeded ADMIN, the example scenarios, and the real backend on a
high port with every inference provider faked — no GPU, no model, no LiveKit.

Dev tooling, like `_common.py`. The stack is **never** the demo's or the test suite's:

* its compose project is `sim112load` (`--project`), its ports are its own (`35432`/`36379` by
  default) and are refused outright when they are one of the demo's, the owner's or the test
  suite's (`FORBIDDEN_PORTS`) or already bound;
* PostgreSQL keeps its data on a compose-managed **volume** (not `tmpfs`, unlike
  `infra/docker-compose.test.yml`): ТЗ ¶164 is a statement about writing to disk, and a RAM-backed
  database would flatter it;
* `down()` is `docker compose ... down -v` plus a SIGTERM (then SIGKILL) of the one backend PID
  this module started — a **captured** `Popen.pid`, never a pattern match.

The seeded ADMIN's password is drawn here (`secrets`), handed to `app.tools.seed_users` through
its environment only, kept in memory, and never printed or written anywhere.
"""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from _common import REPO_ROOT

__all__ = [
    "DEFAULT_API_PORT",
    "DEFAULT_PG_PORT",
    "DEFAULT_PROJECT",
    "DEFAULT_REDIS_PORT",
    "FORBIDDEN_PORTS",
    "OwnStack",
    "StackConfig",
    "StackError",
    "backend_env",
    "compose_yaml",
    "port_refusal",
    "read_rss_mb",
]

DEFAULT_PROJECT = "sim112load"
DEFAULT_PG_PORT = 35432
DEFAULT_REDIS_PORT = 36379
DEFAULT_API_PORT = 18190

#: The demo (5180/8120/25432/26379/17880), the owner's own services (8000/8001/8011/8012/5000),
#: the test suite's compose (55432/56379), the dev stack's (15432/6379/7880) and the UI-run
#: recipe's backend (8100): a load run never binds any of them, even when one happens to be free.
FORBIDDEN_PORTS = frozenset(
    {5000, 5180, 6379, 7880, 8000, 8001, 8011, 8012, 8100, 8120, 15432, 17880, 25432, 26379}
    | {55432, 56379}
)

_DB_USER = "sim"
_DB_NAME = "sim_load"
_ADMIN_USERNAME = "admin"


class StackError(RuntimeError):
    """The scratch stack could not be brought up; the message is the benchmark's `reason`."""


@dataclass(frozen=True)
class StackConfig:
    """Where the scratch stack lives."""

    project: str = DEFAULT_PROJECT
    pg_port: int = DEFAULT_PG_PORT
    redis_port: int = DEFAULT_REDIS_PORT
    api_port: int = DEFAULT_API_PORT
    #: `SIM_SIM_TICK_MS` of the backend under test — the shipped default.
    tick_ms: int = 500
    with_backend: bool = True


def port_refusal(port: int) -> str | None:
    """Why `port` may not be used for the scratch stack, or `None` when it may."""
    if port in FORBIDDEN_PORTS:
        return f"port {port} belongs to the demo, the owner or another stack; pick another"
    if not 1024 < port < 65536:
        return f"port {port} is outside 1025..65535"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return f"port {port} is already in use"
    return None


def compose_yaml(pg_port: int, redis_port: int, db_password: str) -> str:
    """The two-service compose file: loopback-only ports, a data volume for PostgreSQL."""
    return f"""services:
  postgres:
    image: postgres:16
    init: true
    environment:
      POSTGRES_USER: {_DB_USER}
      POSTGRES_PASSWORD: {db_password}
      POSTGRES_DB: {_DB_NAME}
    ports:
      - "127.0.0.1:{pg_port}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      # Over TCP: the image's first-boot init server listens on the socket only, so a socket probe
      # reports "healthy" before the real server has started and the migration hits a reset.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U {_DB_USER} -d {_DB_NAME}"]
      interval: 2s
      timeout: 2s
      retries: 30
  redis:
    image: redis:7
    ports:
      - "127.0.0.1:{redis_port}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 30
volumes:
  pgdata: {{}}
"""


def backend_env(
    *,
    database_url: str,
    redis_url: str,
    api_port: int,
    data_dir: Path,
    jwt_secret: str,
    tick_ms: int,
) -> dict[str, str]:
    """The backend's environment: fake voice/LLM providers, no inference gate, no `.env` file.

    The same recipe the I3/I4 UI checks ran the backend with (`_common.md`), plus the runner left
    **on** (the default): the D7 tick of every ACTIVE session is part of the load being measured.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith("SIM_")}
    env.update(
        {
            "SIM_ENV_FILE": "",
            "SIM_DATABASE_URL": database_url,
            "SIM_REDIS_URL": redis_url,
            "SIM_JWT_SECRET": jwt_secret,
            "SIM_API_HOST": "127.0.0.1",
            "SIM_API_PORT": str(api_port),
            "SIM_CALL_TRANSPORT": "fake",
            "SIM_ASR_PROVIDER": "fake",
            "SIM_LLM_PROVIDER": "fake",
            "SIM_TTS_PROVIDER": "fake",
            "SIM_EXPLANATION_LLM_PROVIDER": "fake",
            "SIM_VAD_PROVIDER": "energy",
            "SIM_REQUIRE_INFERENCE_READY": "false",
            "SIM_RUNNER_ENABLED": "true",
            "SIM_SIM_TICK_MS": str(tick_ms),
            "SIM_DATA_DIR": str(data_dir),
            "SIM_LIVEKIT_URL": "ws://127.0.0.1:1",
            "SIM_LIVEKIT_API_KEY": "load-bench-unused",
            "SIM_LIVEKIT_API_SECRET": "load-bench-unused-secret-0123456789",
            "SIM_LLM_BASE_URL": "http://127.0.0.1:1/v1",
            "SIM_CORS_ALLOW_ORIGINS": "[]",
            "SIM_LOG_FORMAT": "text",
        }
    )
    return env


def read_rss_mb(pid: int) -> float | None:
    """`VmRSS` of `pid` in MiB from `/proc/<pid>/status`, or `None` when it cannot be read."""
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


@dataclass
class OwnStack:
    """`with OwnStack(config) as stack:` — up on enter, `down -v` and backend killed on exit."""

    config: StackConfig = field(default_factory=StackConfig)
    keep: bool = False
    workdir: Path | None = None
    backend: subprocess.Popen[bytes] | None = None
    admin_username: str = _ADMIN_USERNAME
    _admin_password: str = field(default="", repr=False)
    _db_password: str = field(default="", repr=False)
    _jwt_secret: str = field(default="", repr=False)
    _compose_file: Path | None = None
    _log_handle: object | None = None

    # -- addresses ---------------------------------------------------------------------------

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{_DB_USER}:{self._db_password}@127.0.0.1:"
            f"{self.config.pg_port}/{_DB_NAME}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://127.0.0.1:{self.config.redis_port}/0"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.config.api_port}"

    @property
    def admin_password(self) -> str:
        return self._admin_password

    @property
    def backend_pid(self) -> int | None:
        return None if self.backend is None else self.backend.pid

    @property
    def backend_log(self) -> Path | None:
        return None if self.workdir is None else self.workdir / "backend.log"

    # -- lifecycle ---------------------------------------------------------------------------

    def __enter__(self) -> OwnStack:
        try:
            self.up()
        except BaseException:
            self.down()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        self.down()

    def up(self) -> None:
        if shutil.which("docker") is None:
            raise StackError("docker is not installed; the scratch stack cannot start")
        ports = [self.config.pg_port, self.config.redis_port]
        if self.config.with_backend:
            ports.append(self.config.api_port)
        for port in ports:
            refusal = port_refusal(port)
            if refusal is not None:
                raise StackError(refusal)
        self._db_password = secrets.token_urlsafe(16)
        self._admin_password = secrets.token_urlsafe(18)
        self._jwt_secret = secrets.token_urlsafe(32)
        self.workdir = Path(tempfile.mkdtemp(prefix="sim112load-"))
        self._compose_file = self.workdir / "compose.yml"
        self._compose_file.write_text(
            compose_yaml(self.config.pg_port, self.config.redis_port, self._db_password),
            encoding="utf-8",
        )
        self._compose("up", "-d", "--wait", timeout=300)
        env = self._env()
        self._run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(REPO_ROOT / "backend" / "alembic.ini"),
                "-x",
                f"url={self.database_url}",
                "upgrade",
                "head",
            ],
            env,
            "alembic upgrade head",
        )
        seed_env = dict(env)
        seed_env["SIM_SEED_ADMIN_PASSWORD"] = self._admin_password
        # `seed_users` refuses a missing password for any of its three accounts; the other two
        # are never logged into by the benchmark, so they get throwaway random values.
        seed_env["SIM_SEED_TRAINEE_PASSWORD"] = secrets.token_urlsafe(18)
        seed_env["SIM_SEED_INSTRUCTOR_PASSWORD"] = secrets.token_urlsafe(18)
        self._run([sys.executable, "-m", "app.tools.seed_users"], seed_env, "seed_users")
        self._run(
            [
                sys.executable,
                "-m",
                "app.tools.import_scenarios",
                str(REPO_ROOT / "scenarios" / "examples"),
            ],
            env,
            "import_scenarios",
        )
        if self.config.with_backend:
            self._start_backend(env)

    def down(self) -> None:
        if self.backend is not None:
            _terminate(self.backend)
            self.backend = None
        if self._log_handle is not None:
            self._log_handle.close()  # type: ignore[attr-defined]
            self._log_handle = None
        if self.keep:
            return
        if self._compose_file is not None and self._compose_file.exists():
            try:
                self._compose("down", "-v", "--remove-orphans", timeout=180, check=False)
            except subprocess.TimeoutExpired:
                # `down()` runs from `__exit__`: a slow `compose down` is reported, never raised.
                print("load stack: docker compose down timed out", file=sys.stderr)
        if self.workdir is not None:
            shutil.rmtree(self.workdir, ignore_errors=True)

    # -- internals ---------------------------------------------------------------------------

    def _env(self) -> dict[str, str]:
        assert self.workdir is not None
        return backend_env(
            database_url=self.database_url,
            redis_url=self.redis_url,
            api_port=self.config.api_port,
            data_dir=self.workdir / "data",
            jwt_secret=self._jwt_secret,
            tick_ms=self.config.tick_ms,
        )

    def _compose(self, *args: str, timeout: int, check: bool = True) -> None:
        assert self._compose_file is not None
        command = ["docker", "compose", "-p", self.config.project, "-f", str(self._compose_file)]
        completed = subprocess.run(
            [*command, *args], capture_output=True, text=True, timeout=timeout, check=False
        )
        if check and completed.returncode != 0:
            tail = (completed.stderr or completed.stdout).strip().splitlines()[-5:]
            raise StackError(f"docker compose {args[0]} failed: {' | '.join(tail)}")

    def _run(self, command: list[str], env: dict[str, str], label: str) -> None:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout).strip().splitlines()[-5:]
            raise StackError(f"{label} failed: {' | '.join(tail)}")

    def _start_backend(self, env: dict[str, str]) -> None:
        assert self.workdir is not None
        (self.workdir / "data").mkdir(parents=True, exist_ok=True)
        log_path = self.workdir / "backend.log"
        handle = log_path.open("wb")
        self._log_handle = handle
        # `python -m uvicorn` straight from this interpreter (the one `uv run` chose), so the PID
        # captured below IS the server process — no `uv` wrapper in between to sample by mistake.
        self.backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.api.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.config.api_port),
                "--no-access-log",
            ],
            cwd=REPO_ROOT / "backend",
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 90
        url = f"{self.base_url}/api/v1/health/live"
        while time.monotonic() < deadline:
            if self.backend.poll() is not None:
                raise StackError(f"the backend exited with {self.backend.returncode}; see its log")
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        raise StackError("the backend did not answer /api/v1/health/live within 90 s")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM the captured PID, then SIGKILL after 15 s — never a name/pattern match."""
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
