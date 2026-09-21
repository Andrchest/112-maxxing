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
    data_dir: str = "data"
    require_inference_ready: bool = True
    sim_tick_ms: int = 500
    sim_runner_lock_ttl_s: int = 30
    sim_runner_lock_refresh_s: int = 10
    instance_id: str = Field(default_factory=lambda: _PROCESS_INSTANCE_ID)
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
