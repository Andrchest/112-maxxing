"""`infra/docker-compose.tls.yml` (I7 E49, Q-E27-1): once the `tls` profile is active, the plain
http ports 5173/8100/7880 must not be published — only the Caddy https entrypoint on 443 is.

Parses the raw override YAML with PyYAML, like `test_compose_file.py`'s own base-file checks
(deliberately no Docker daemon dependency for a unit test under `make gate`); `make compose-check`
is the separate gate step that renders this file through the real `docker compose` CLI layered on
the base file (and, in a second invocation, on `docker-compose.gpu.yml` too — see the Makefile's
"I7 E49" section). The override uses the compose-spec `!override` merge tag (proven empirically,
in the I7 E49 report, to fully replace a sequence field on merge — a plain `null` or an ordinary
list does not: Compose's default merge CONCATENATES `ports:` across `-f` files), so this module
registers a trivial constructor for that tag before parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[4] / "infra" / "docker-compose.yml"
TLS_OVERRIDE_PATH = COMPOSE_PATH.with_name("docker-compose.tls.yml")

PLAIN_HTTP_SERVICES = ("backend", "frontend", "livekit")


class _ComposeLoader(yaml.SafeLoader):
    """`yaml.SafeLoader` plus the compose-spec `!override` merge tag, treated as transparent."""


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!override", _construct_override)


@pytest.fixture(scope="module")
def tls_override_doc() -> dict:
    return yaml.load(TLS_OVERRIDE_PATH.read_text(encoding="utf-8"), Loader=_ComposeLoader)


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_the_override_touches_only_the_plain_http_services(tls_override_doc: dict) -> None:
    assert set(tls_override_doc["services"]) == set(PLAIN_HTTP_SERVICES)


def test_backend_and_frontend_publish_no_port_at_all(tls_override_doc: dict) -> None:
    for name in ("backend", "frontend"):
        assert tls_override_doc["services"][name]["ports"] == []


def test_livekit_keeps_its_two_media_ports_but_not_signalling(tls_override_doc: dict) -> None:
    """7880 (http/websocket signalling) drops; 7881 (tcp fallback) and 7882/udp (media) stay —
    WebRTC media never goes through the edge (`docs/RUNBOOK.md`'s HTTPS section)."""
    ports = tls_override_doc["services"]["livekit"]["ports"]
    assert sorted(ports) == sorted(["7881:7881", "7882:7882/udp"])
    assert not any(str(mapping).startswith("7880") for mapping in ports)


def test_every_overridden_service_exists_in_the_base_file_and_normally_publishes_a_port(
    tls_override_doc: dict, compose_doc: dict
) -> None:
    """The override cannot silently go stale against a renamed/removed base service."""
    for name in PLAIN_HTTP_SERVICES:
        assert name in compose_doc["services"], f"{name} no longer exists in the base compose file"
        assert compose_doc["services"][name].get("ports"), (
            f"{name} publishes no port in the base file any more — the tls override is now a no-op"
        )
