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
    # -- the voice turn path (HLD `50-voice-pipeline.md` §4.1, D9, SPEC §17) ------------------
    # SPEC §17: "Make this configuration, not a hard-coded magic value." Every key of §4.1's
    # table gets one `SIM_VOICE_*` variable; `app.application.voice.config.VoiceTurnConfig`
    # validates the ranges and the cross-field rules, and the `TurnDetector` reads nothing else.
    # TODO(E12): the active model profile's `voice_turn.*` block overlays this env block.
    voice_speech_start_threshold: float = 0.55
    voice_speech_end_threshold: float = 0.35
    voice_speech_start_min_ms: int = 96
    voice_endpoint_silence_ms: int = 300
    voice_pre_roll_ms: int = 300
    voice_barge_in_min_speech_ms: int = 120
    voice_max_turn_ms: int = 30000
    voice_min_turn_ms: int = 200
    voice_vad_frame_ms: int = 32
    voice_trailing_pad_ms: int = 100
    voice_outbound_queue_ms: int = 200
    voice_tts_chunk_ms: int = 40
    voice_partial_asr_enabled: bool = True
    voice_partial_interval_ms: int = 500
    voice_sample_rate: int = 16000
    #: `VOICE_JOIN_RETRY_MS` of §40.6: how often the backend re-publishes `voice:join` while a
    #: call is RINGING (D9, E11-B). The default is §40.6's, literally.
    voice_join_retry_ms: int = 2000
    #: How long the voice agent's `voice:health:vad` heartbeat key lives (HLD 60 §4.3).
    voice_health_heartbeat_s: int = 5
    voice_health_ttl_s: int = 15
    # -- E11-B: the LiveKit access tokens the backend mints (D9, `openapi.yaml`) ---------------
    #: `createVoiceToken` lifetime. Ten minutes: long enough to join a call that is still ringing,
    #: short enough that a leaked token is worthless. The token is re-minted, not refreshed.
    livekit_token_ttl_minutes: int = 10
    #: The URL a BROWSER dials, which is not always the one this process dials. Under
    #: `infra/docker-compose.yml` the backend and the voice-agent reach the SFU at its
    #: compose-internal name (`SIM_LIVEKIT_URL`, e.g. `ws://livekit:7880`) while the trainee's
    #: browser must be told a URL that resolves on their machine (`ws://localhost:7880`).
    #: `VoiceTokenResponse.livekit_url` carries this one; the readiness probe and the voice-agent
    #: keep using `livekit_url`. Empty (the default) means "they are the same", which is what a
    #: plain local run wants — see `livekit_browser_url`.
    livekit_public_url: str = ""

    @property
    def livekit_browser_url(self) -> str:
        """`SIM_LIVEKIT_PUBLIC_URL` when it is set, else `SIM_LIVEKIT_URL` (see that field)."""
        return self.livekit_public_url or self.livekit_url


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide, cached `Settings` instance."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
