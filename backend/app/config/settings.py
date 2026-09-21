"""Process configuration.

All settings are read from the environment (and `.env` in local dev) with the `SIM_` prefix, per
D1/D8. `.env.example` documents every variable with a fake-but-shaped default value; no real secret
ever gets a default here.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROCESS_INSTANCE_ID: str = secrets.token_hex(8)
"""This process's identity, drawn once at import.

`SimulationRunner` writes it into `lock:session:{id}:runner` (§40.6) and compares against it on
every refresh and release, so "the owning backend instance" is a real per-process value and two
instances on one machine can never mistake each other's lock for their own. `SIM_INSTANCE_ID`
overrides it when a deployment wants a stable, human-readable name.
"""


class Settings(BaseSettings):
    """Backend process configuration, sourced from environment variables prefixed `SIM_`."""

    model_config = SettingsConfigDict(env_prefix="SIM_", env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    jwt_secret: str
    #: Loopback by default (SPEC §41, "local operation"): the API is not exposed to the network
    #: unless a deployment says so. Ports 8000/8001 on the developer machine belong to another
    #: project, so the default is 8100 — see this repository's E7-A task report.
    api_host: str = "127.0.0.1"
    api_port: int = 8100
    #: D8's bearer-token lifetime. Twelve hours: longer than the longest training day, so a
    #: session is never interrupted by a re-login, and short enough that a leaked token expires.
    jwt_ttl_minutes: int = 720
    #: The Vite dev server (D12). The compose deployment serves the frontend from the same
    #: origin, so this list is a development affordance, not a production one.
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    #: Which `CallTransportStatus` adapter the composition root wires (D9).
    #: `"livekit"` arrives in E11; until then it raises a `NotImplementedError` naming that epic.
    call_transport: str = "fake"
    #: D7's "one task per ACTIVE session". API tests set it false and drive `tick_session`
    #: explicitly, so no background task can outlive a test.
    runner_enabled: bool = True
    data_dir: str = "data"
    require_inference_ready: bool = True
    sim_tick_ms: int = 500
    sim_runner_lock_ttl_s: int = 30
    sim_runner_lock_refresh_s: int = 10
    #: `IDEMPOTENCY_TTL_S` of §40.6: how long `idempotency:{user_id}:{client_command_id}` keeps
    #: the first response body of a command, so a retried `setCardField` is a no-op rather than a
    #: second revision. Losing the key only re-evaluates the command (§40.6), never corrupts it.
    idempotency_ttl_s: int = 300
    instance_id: str = Field(default_factory=lambda: _PROCESS_INSTANCE_ID)
    #: `WS_REPLAY_MAX_EVENTS` (§40.3 "Replay bounds"): rows per replay page. There is no upper
    #: bound on the total replayed — a client away for the whole session gets the whole session;
    #: this only bounds one page, so a long replay never blocks the event loop.
    ws_replay_max_events: int = 5000
    #: §40.2 `heartbeat`: "Every 15 seconds when no event was pushed."
    ws_heartbeat_s: int = 15
    #: §40.2 client→server frames: "more than 10 frames per second closes the socket (`4429`)".
    ws_max_frames_per_s: int = 10
    #: `SESSION_CACHE_TTL_S` (§40.6): the TTL of `session:{id}:last_seq_no` and
    #: `session:{id}:call_state`. Both are read caches; losing them costs one PostgreSQL read.
    session_cache_ttl_s: int = 3600
    model_profile: str = "DEV_3060TI"
    recording_retention_days: int = 30
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    llm_base_url: str


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide, cached `Settings` instance."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
