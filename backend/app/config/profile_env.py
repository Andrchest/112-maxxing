"""Emits the active model profile's `llm.*` block as `SIM_LLAMA_*` env lines.

`make profile-env` runs this as `uv run python -m app.config.profile_env --profile NAME --emit-env`
and writes the output to `infra/.env.profile`. `infra/docker-compose.yml`'s `llama-server` service
(and `make run-llama-server` for a host run) load that file as an env source for
`infra/scripts/llama-server-entrypoint.sh` — the `ggml-org/llama.cpp` CUDA server image has no
Python of its own to read a profile YAML directly (docs/hld/60-inference-ops.md §8/§9), so this is
the one place a profile's LLM block is translated into the flags that script computes.

Owner: E18-E (infra/compose slice of epic E18). This module deliberately imports only
`app.config.profile.load_profile` — E18-A's module (HLD 60 §2, the E18 brief's ruling R1) — and
nothing else from it, so it stays a thin, single-purpose adapter. If `app.config.profile` is not
yet importable (a workspace-race with E18-A), this CLI fails with that ImportError rather than
inventing a flag value (SPEC §26/§27: never invent a config or benchmark number).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any


def _emit_lines(profile: Any) -> list[str]:
    """Build the `KEY=VALUE` lines for `infra/scripts/llama-server-entrypoint.sh`.

    Field names below are exactly HLD 60 §2.1's `llm.*` key reference table
    (`model_path`, `model_name`, `n_ctx`, `parallel_slots`, `n_gpu_layers`, `n_batch`, `n_ubatch`,
    `flash_attention`, `kv_cache_type`) — the interface `ModelProfile` (R1) is required to expose.
    """
    llm = profile.llm
    return [
        f"SIM_MODEL_PROFILE={profile.profile_name}",
        f"SIM_LLAMA_MODEL_PATH={llm.model_path}",
        f"SIM_LLAMA_ALIAS={llm.model_name}",
        f"SIM_LLAMA_N_CTX={llm.n_ctx}",
        f"SIM_LLAMA_PARALLEL={llm.parallel_slots}",
        f"SIM_LLAMA_N_GPU_LAYERS={llm.n_gpu_layers}",
        f"SIM_LLAMA_N_BATCH={llm.n_batch}",
        f"SIM_LLAMA_N_UBATCH={llm.n_ubatch}",
        f"SIM_LLAMA_FLASH_ATTENTION={llm.flash_attention}",
        f"SIM_LLAMA_KV_CACHE_TYPE={llm.kv_cache_type}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the active model profile's llm.* block as SIM_LLAMA_* env lines."
    )
    parser.add_argument("--profile", required=True, help="profile name, e.g. DEV_3060TI")
    parser.add_argument(
        "--emit-env",
        action="store_true",
        help="print KEY=VALUE lines to stdout (the only supported mode today)",
    )
    args = parser.parse_args(argv)

    if not args.emit_env:
        parser.error("--emit-env is required")

    # Imported here, not at module scope: keeps `python -m app.config.profile_env --help` working
    # (and this module importable for its own unit test, which exercises `_emit_lines` directly
    # against a stub) even before `app.config.profile` exists on a given checkout.
    from app.config.profile import load_profile

    profile = load_profile(args.profile)
    for line in _emit_lines(profile):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
