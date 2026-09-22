"""`infra/docker-compose.yml` structural checks (E18-E, SPEC §36, D1, HLD 60 §9).

Parses the raw compose YAML with PyYAML — deliberately NOT `docker compose config` (no Docker
daemon dependency for a unit test that runs under `make gate`; `make compose-check` is the separate
gate step that actually renders the file through the real `docker compose` CLI, see the Makefile).
`${VAR:-default}` interpolation strings are therefore left unresolved here and are inspected as
plain text, which is sufficient for every assertion below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docker-compose.yml"

SPEC_36_SEVEN = {
    "postgres",
    "redis",
    "livekit",
    "backend",
    "frontend",
    "llama-server",
    "voice-agent",
}
ADDITIVE_EIGHTH = "tts-qwen3"

# The GPU process PID 1082982's owner and everything on these ports belongs to another project on
# the dev machine (this task's brief, MACHINE RULES) — never bound anywhere in this file.
NEVER_BIND_PORTS = {"8000", "8001", "8011", "8012", "8016"}

NO_HOST_PORT_SERVICES = {"llama-server", "voice-agent", ADDITIVE_EIGHTH}


@pytest.fixture(scope="module")
def compose_raw_text() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose_doc(compose_raw_text: str) -> dict:
    return yaml.safe_load(compose_raw_text)


def test_service_names_are_exactly_the_spec_seven_plus_the_additive_eighth(
    compose_doc: dict,
) -> None:
    services = set(compose_doc["services"])
    assert services == SPEC_36_SEVEN | {ADDITIVE_EIGHTH}


def test_the_eighth_service_is_gated_behind_a_compose_profile_so_a_plain_up_is_the_seven(
    compose_doc: dict,
) -> None:
    eighth = compose_doc["services"][ADDITIVE_EIGHTH]
    assert eighth.get("profiles") == ["qwen3-tts"]
    for name in SPEC_36_SEVEN:
        assert "profiles" not in compose_doc["services"][name], (
            f"{name} must start with a plain `docker compose up` (no profile gate)"
        )


def test_no_never_bind_port_appears_anywhere_in_a_published_port_mapping(compose_doc: dict) -> None:
    # Scans the parsed `ports:` lists only (not the whole file's prose/comments, which legitimately
    # name the forbidden ports to explain why they are avoided).
    for name, svc in compose_doc["services"].items():
        for mapping in svc.get("ports", []):
            for port in NEVER_BIND_PORTS:
                assert port not in str(mapping), (
                    f"{name} must never bind forbidden port {port} (got {mapping!r})"
                )


def test_llama_server_voice_agent_and_tts_qwen3_publish_no_host_port(compose_doc: dict) -> None:
    for name in NO_HOST_PORT_SERVICES:
        svc = compose_doc["services"][name]
        assert not svc.get("ports"), f"{name} must publish no host port (HLD 60 §9, SPEC §41)"


def test_every_service_declares_a_healthcheck(compose_doc: dict) -> None:
    for name, svc in compose_doc["services"].items():
        assert "healthcheck" in svc, f"{name} has no healthcheck and no stated reason for skipping"


def test_no_literal_secret_every_secret_bearing_value_is_env_interpolated(
    compose_raw_text: str,
) -> None:
    secret_key_pattern = re.compile(
        r"^\s*(LIVEKIT_KEYS|POSTGRES_PASSWORD|SIM_JWT_SECRET|SIM_LIVEKIT_API_SECRET"
        r"|SIM_LIVEKIT_API_KEY|SIM_SEED_\w+_PASSWORD)\s*:\s*(.+)$",
        re.MULTILINE,
    )
    matches = secret_key_pattern.findall(compose_raw_text)
    assert matches, "expected at least one secret-bearing key in the compose file"
    for key, value in matches:
        assert "${" in value, f"{key}'s value {value!r} is not environment-interpolated"


def test_gpu_services_use_the_nvidia_runtime(compose_doc: dict) -> None:
    for name in ("llama-server", "voice-agent", ADDITIVE_EIGHTH):
        svc = compose_doc["services"][name]
        assert svc.get("runtime") == "nvidia", f"{name} must use the nvidia container runtime"


def test_models_dir_is_mounted_read_only_on_every_gpu_service(compose_doc: dict) -> None:
    for name in ("llama-server", "voice-agent", ADDITIVE_EIGHTH):
        volumes = compose_doc["services"][name].get("volumes", [])
        models_mounts = [v for v in volumes if isinstance(v, str) and "/models:ro" in v]
        assert models_mounts, f"{name} must mount MODELS_DIR read-only at /models"


def test_llama_server_command_is_the_committed_entrypoint_script(compose_doc: dict) -> None:
    llama = compose_doc["services"]["llama-server"]
    entrypoint = llama.get("entrypoint")
    assert entrypoint is not None
    assert any("entrypoint.sh" in part for part in entrypoint)
