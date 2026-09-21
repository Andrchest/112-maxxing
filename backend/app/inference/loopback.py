"""`validate_loopback_base_url` — the one SPEC §41 loopback/compose-internal guard.

Every adapter whose `base_url` targets a local worker process (`LlamaCppClient`, `Qwen3TTS`, and
any future one) must refuse a `base_url` that is not loopback or a configured compose-internal
service name, checked at **construction**, never at call time, and with **no DNS resolution** — a
host that merely *looks* loopback (`localhost.evil.com`, `127.0.0.1.nip.io`) is rejected exactly
because no resolution happens (SPEC §41).

MANAGER RULING (E14 close-out, item 5): E14-B duplicated this logic in
`app.inference.tts.qwen3_tts.validate_tts_qwen3_base_url` because `llama_cpp_client.py` was
outside its brief's files; this module is the single place the rule now lives. Both
`app.inference.llm.llama_cpp_client.validate_llm_base_url` and
`app.inference.tts.qwen3_tts.validate_tts_qwen3_base_url` stay importable under their old names —
each is now a thin wrapper around `validate_loopback_base_url` below, supplying its own error type
(`ExternalInferenceEndpointError` / `TtsQwen3EndpointError`) and its own `SIM_*_BASE_URL` name for
the message — so every existing caller and test is unaffected. Behaviour is byte-for-byte the same
as before this move.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

__all__ = ["validate_loopback_base_url"]


def validate_loopback_base_url(
    base_url: str,
    *,
    what: str,
    allowed_internal_hosts: Sequence[str],
    error: Callable[[str], Exception],
) -> None:
    """SPEC §41: `base_url`'s host must be loopback or a configured compose-internal name.

    * `what` — the `SIM_*_BASE_URL` env var name, used only to word the error message.
    * `allowed_internal_hosts` — the caller's configured compose service name allow-list.
    * `error` — the caller's own exception type; called with the message and raised here (so a
      `TtsQwen3EndpointError` and an `ExternalInferenceEndpointError` never need to know about
      each other, D2's "adapters may import each other's ports, not each other's internals").
    """
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        raise error(f"{what}={base_url!r} has no host (SPEC §41)")
    if host in allowed_internal_hosts:
        return
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise error(
            f"{what} host {host!r} is not loopback, not 'localhost' and not one of "
            f"the configured compose-internal hosts {tuple(allowed_internal_hosts)!r} (SPEC §41)"
        ) from exc
    if not address.is_loopback:
        raise error(f"{what} host {host!r} ({address}) is not a loopback address (SPEC §41)")
