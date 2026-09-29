"""I4 E27 — the TLS edge (docs/hld/71-i4-wave4.md §71.4, D32; puml/i4-tls-edge-topology.puml).

Three artifacts, checked without a Docker daemon (the same rule as `test_compose_file.py`):

* the `edge` service in `infra/docker-compose.yml` (parsed YAML);
* its routes in `infra/edge/Caddyfile` (the directive lines, comments stripped);
* `infra/scripts/make-certs.sh`, run for real into a temporary directory (needs `openssl`, which
  every supported host has; skipped otherwise), and its output inspected with `openssl` itself.

The browser half — `window.isSecureContext` over `https://<LAN-IP>` and the ДДС phone widget
joining LiveKit over `wss://` — is `frontend/e2e/tls-edge.e2e.ts` (docs/RUNBOOK.md, «HTTPS в
классе»).
"""

from __future__ import annotations

import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
CADDYFILE_PATH = REPO_ROOT / "infra" / "edge" / "Caddyfile"
MAKE_CERTS = REPO_ROOT / "infra" / "scripts" / "make-certs.sh"
CERTS_GITIGNORE = REPO_ROOT / "infra" / "certs" / ".gitignore"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")


@pytest.fixture(scope="module")
def compose_services() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))["services"]
    return services


@pytest.fixture(scope="module")
def edge(compose_services: dict[str, Any]) -> dict[str, Any]:
    service: dict[str, Any] = compose_services["edge"]
    return service


@pytest.fixture(scope="module")
def caddy_lines() -> list[str]:
    lines = []
    for raw in CADDYFILE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


# -- the compose service --------------------------------------------------------------------------


def test_the_edge_is_profiled_so_a_plain_up_needs_no_certificate(edge: dict[str, Any]) -> None:
    assert edge["profiles"] == ["tls"]


def test_the_edge_image_is_caddy_pinned_by_digest(edge: dict[str, Any]) -> None:
    assert re.fullmatch(r"caddy:2\.\d+\.\d+@sha256:[0-9a-f]{64}", edge["image"])


def test_the_edge_publishes_https_on_443_by_default_and_nothing_else(edge: dict[str, Any]) -> None:
    assert edge["ports"] == ["${SIM_EDGE_HTTPS_BIND:-0.0.0.0}:${SIM_EDGE_HTTPS_PORT:-443}:443"]


def test_the_edge_mounts_the_caddyfile_and_only_the_server_certificate_and_key(
    edge: dict[str, Any],
) -> None:
    volumes = edge["volumes"]
    assert "./edge/Caddyfile:/etc/caddy/Caddyfile:ro" in volumes
    binds = [v for v in volumes if isinstance(v, dict)]
    assert {(b["source"], b["target"]) for b in binds} == {
        ("./certs/server.crt", "/certs/server.crt"),
        ("./certs/server.key", "/certs/server.key"),
    }
    for bind in binds:
        assert bind["read_only"] is True
        # A missing certificate fails `up` loudly instead of Docker creating a directory there.
        assert bind["bind"]["create_host_path"] is False
    assert "ca.key" not in yaml.safe_dump(edge), "the CA key never enters a container"


def test_the_edge_upstreams_default_to_the_compose_services(edge: dict[str, Any]) -> None:
    assert edge["environment"] == {
        "SIM_EDGE_FRONTEND_UPSTREAM": "${SIM_EDGE_FRONTEND_UPSTREAM:-frontend:5173}",
        "SIM_EDGE_BACKEND_UPSTREAM": "${SIM_EDGE_BACKEND_UPSTREAM:-backend:8100}",
        "SIM_EDGE_LIVEKIT_UPSTREAM": "${SIM_EDGE_LIVEKIT_UPSTREAM:-livekit:7880}",
    }
    assert set(edge["depends_on"]) == {"frontend", "backend", "livekit"}
    # The container port 443 the `ports:` mapping targets is the Caddyfile's default.
    assert "SIM_EDGE_LISTEN_PORT" not in edge["environment"]


def test_the_edge_healthcheck_goes_through_tls_to_the_backend(edge: dict[str, Any]) -> None:
    probe = " ".join(edge["healthcheck"]["test"])
    assert "https://127.0.0.1/api/v1/health/live" in probe


def test_the_backend_trusts_the_edge_forwarded_headers_and_vite_gets_its_allowed_hosts(
    compose_services: dict[str, Any],
) -> None:
    """Behind the edge the audit log (E25) must still record the user's address, not the edge's;
    and the Vite dev server must accept the server's hostname in the forwarded Host header."""
    backend_env = compose_services["backend"]["environment"]
    assert backend_env["FORWARDED_ALLOW_IPS"] == "${SIM_FORWARDED_ALLOW_IPS:-172.16.0.0/12}"
    frontend_env = compose_services["frontend"]["environment"]
    assert frontend_env["VITE_ALLOWED_HOSTS"] == "${VITE_ALLOWED_HOSTS:-}"


def test_the_sip_gateway_is_not_behind_the_edge(compose_services: dict[str, Any]) -> None:
    """Q-E15-2: the gateway terminates its own SIP over TLS (I7 E44, 5061) beside its plain
    ports; it is never proxied by the edge."""
    assert "sip-gateway" not in compose_services["edge"]["depends_on"]
    assert "5060:5060/udp" in compose_services["sip-gateway"]["ports"]


# -- the Caddyfile routes -------------------------------------------------------------------------


def test_the_caddyfile_serves_tls_on_443_with_the_make_certs_certificate(
    caddy_lines: list[str],
) -> None:
    # 443 unless SIM_EDGE_LISTEN_PORT says otherwise — only the host-run variant sets it.
    assert ":{$SIM_EDGE_LISTEN_PORT:443} {" in caddy_lines
    assert "tls /certs/server.crt /certs/server.key" in caddy_lines
    assert "auto_https off" in caddy_lines  # no ACME, no Caddy-managed CA
    assert "admin off" in caddy_lines


def test_the_caddyfile_compresses_with_zstd_and_gzip(caddy_lines: list[str]) -> None:
    """¶390 REQ-2321: compression at the proxy."""
    assert "encode zstd gzip" in caddy_lines


def _handler_upstream(lines: list[str], opener: str) -> str:
    start = lines.index(opener)
    proxy = lines[start + 1]
    assert proxy.startswith("reverse_proxy "), f"{opener!r} must proxy straight away"
    return proxy.removeprefix("reverse_proxy ")


def test_the_caddyfile_routes_rtc_api_and_everything_else(caddy_lines: list[str]) -> None:
    assert "@livekit path /rtc /rtc/*" in caddy_lines
    assert _handler_upstream(caddy_lines, "handle @livekit {") == (
        "{$SIM_EDGE_LIVEKIT_UPSTREAM:livekit:7880}"
    )
    # `/api/*` covers `/api/v1/ws/...`: reverse_proxy upgrades WebSockets on its own.
    assert _handler_upstream(caddy_lines, "handle /api/* {") == (
        "{$SIM_EDGE_BACKEND_UPSTREAM:backend:8100}"
    )
    assert _handler_upstream(caddy_lines, "handle {") == (
        "{$SIM_EDGE_FRONTEND_UPSTREAM:frontend:5173}"
    )
    # The specific routes come before the catch-all (Caddy's `handle` blocks are mutually
    # exclusive and the bare one is the fallback wherever it is, but the file reads in order).
    assert caddy_lines.index("handle @livekit {") < caddy_lines.index("handle {")
    assert caddy_lines.index("handle /api/* {") < caddy_lines.index("handle {")


def test_no_log_line_writes_a_websocket_credential(caddy_lines: list[str]) -> None:
    """The realtime socket's `?token=` and LiveKit's `?access_token=` are bearer credentials. Both
    the site's access log and the default logger (the proxy's error lines carry the URI too) filter
    them — the E27 proof run found the error lines leaking before the default logger had one."""
    assert "log default {" in caddy_lines
    assert caddy_lines.count("request>uri query {") == 2
    assert caddy_lines.count("replace token REDACTED") == 2
    assert caddy_lines.count("replace access_token REDACTED") == 2


def test_the_env_example_documents_the_wss_livekit_url_and_the_tls_profile() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^#\s*SIM_LIVEKIT_PUBLIC_URL=wss://", text, re.M)
    assert re.search(r"^#\s*COMPOSE_PROFILES=tls\b", text, re.M)
    assert re.search(r"^#\s*VITE_ALLOWED_HOSTS=", text, re.M)


# -- make-certs.sh --------------------------------------------------------------------------------


def test_the_default_certificate_directory_is_git_ignored() -> None:
    lines = CERTS_GITIGNORE.read_text(encoding="utf-8").splitlines()
    assert "*" in lines and "!.gitignore" in lines


def _run_make_certs(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(MAKE_CERTS), *args], capture_output=True, text=True, check=False
    )


def _openssl(*args: str) -> str:
    return subprocess.run(["openssl", *args], capture_output=True, text=True, check=True).stdout


@needs_openssl
def test_make_certs_issues_a_ca_and_a_server_certificate_with_the_lan_sans(
    tmp_path: Path,
) -> None:
    out = tmp_path / "certs"
    result = _run_make_certs("--out", str(out), "--ip", "192.0.2.10", "--host", "sim112.test")
    assert result.returncode == 0, result.stderr

    for name in ("ca.crt", "ca.key", "server.crt", "server.key"):
        assert (out / name).is_file(), name
    for key in ("ca.key", "server.key"):
        assert stat.S_IMODE((out / key).stat().st_mode) == 0o600, key

    # server.crt is the chain Caddy serves: the leaf, then the CA.
    assert (out / "server.crt").read_text().count("BEGIN CERTIFICATE") == 2
    verified = _openssl("verify", "-CAfile", str(out / "ca.crt"), str(out / "server.crt"))
    assert verified.strip().endswith(": OK")

    leaf = _openssl("x509", "-in", str(out / "server.crt"), "-noout", "-text")
    sans = re.search(r"Subject Alternative Name:.*?\n\s*(.+)", leaf)
    assert sans is not None
    assert set(sans.group(1).split(", ")) == {
        "DNS:localhost",
        "IP Address:127.0.0.1",
        "IP Address:0:0:0:0:0:0:0:1",
        "DNS:sim112.test",
        "IP Address:192.0.2.10",
    }
    assert "TLS Web Server Authentication" in leaf
    assert re.search(r"Basic Constraints: critical\s*\n\s*CA:FALSE", leaf)

    ca = _openssl("x509", "-in", str(out / "ca.crt"), "-noout", "-text")
    assert re.search(r"Basic Constraints: critical\s*\n\s*CA:TRUE, pathlen:0", ca)
    # The teacher compares this on each classroom PC when installing ca.crt (RUNBOOK).
    assert "sha256 fingerprint=" in result.stdout.lower()


@needs_openssl
def test_make_certs_rerun_keeps_the_ca_so_classroom_pcs_need_no_reinstall(tmp_path: Path) -> None:
    out = tmp_path / "certs"
    assert _run_make_certs("--out", str(out), "--ip", "192.0.2.10").returncode == 0
    ca_before = (out / "ca.crt").read_bytes()
    server_before = (out / "server.crt").read_bytes()

    rerun = _run_make_certs("--out", str(out), "--ip", "198.51.100.7")
    assert rerun.returncode == 0, rerun.stderr
    assert "reusing the existing local CA" in rerun.stdout
    assert (out / "ca.crt").read_bytes() == ca_before
    assert (out / "server.crt").read_bytes() != server_before
    leaf = _openssl("x509", "-in", str(out / "server.crt"), "-noout", "-ext", "subjectAltName")
    assert "198.51.100.7" in leaf and "192.0.2.10" not in leaf

    fresh = _run_make_certs("--out", str(out), "--ip", "198.51.100.7", "--new-ca")
    assert fresh.returncode == 0, fresh.stderr
    assert (out / "ca.crt").read_bytes() != ca_before


@needs_openssl
def test_make_certs_refuses_a_malformed_ip_before_writing_anything(tmp_path: Path) -> None:
    out = tmp_path / "certs"
    result = _run_make_certs("--out", str(out), "--ip", "not-an-ip")
    assert result.returncode == 2
    assert "not an IP address" in result.stderr
    assert not out.exists()
