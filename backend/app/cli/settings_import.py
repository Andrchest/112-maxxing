"""`python -m app.cli settings_import --file <xml> [--out <path>]` (I5 E37, Q-E16-1).

The other half of `exportSettingsXml` (`app.api.routers.admin`, ADMIN-only HTTP read): this half
is CLI only, on purpose (this epic's ruling) — importing settings changes what the *next* restart
of the backend/voice-agent reads, which is an operator's call at the console, not an HTTP write any
authenticated ADMIN session could fire by accident.

What it does, in order:

1. reads `--file` and validates it with `app.config.settings_xml.settings_env_lines` — the same
   module `exportSettingsXml` renders with, so export and import can never drift about what a name
   or a value means (schema, known `SIM_*` name, never a secret, the value fits its `Settings`
   field's own type);
2. on success, writes `NAME=value\\n` lines to `--out` (default `infra/.env.settings`, relative to
   the process's current working directory — `make settings-import` runs `uv run` from the repo
   root, so the default lands next to `infra/.env.profile`'s own gitignored sibling);
3. prints how many settings were written and exits `0`. Any failure (bad XML, unknown/secret name,
   a value that does not fit its type, an unwritable `--out`) prints one line to stderr and exits
   `2` — **nothing is written on failure**, not even a partial file (the whole document is
   validated before the first byte of `--out` is touched).

**Never touches the running process** (this epic's ruling, literally): this module opens no
socket, calls `get_settings()` nowhere, and the only environment variables it ever sets are the
validation probe's own, inside `settings_xml._temporary_env`'s `with` block — restored before this
function's `main()` returns either way. `infra/.env.settings` only takes effect the next time a
process that reads it (an updated `infra/docker-compose.yml` `env_file:` entry, or an operator
folding it into `.env` for a host run — see `docs/RUNBOOK.md`) is started.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config.settings_xml import SettingsXmlError, settings_env_lines

__all__ = ["main", "run_settings_import"]

DEFAULT_OUT_PATH = "infra/.env.settings"


def run_settings_import(xml_text: str, *, out_path: Path) -> int:
    """Validate `xml_text` and write it to `out_path` as `NAME=value` lines. Returns the count."""
    lines = settings_env_lines(xml_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli settings_import",
        description="Validate and apply an exportSettingsXml document (Q-E16-1).",
    )
    parser.add_argument(
        "--file", required=True, type=str, help="the XML file exportSettingsXml produced"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=DEFAULT_OUT_PATH,
        help=f"where to write the env file (default: {DEFAULT_OUT_PATH})",
    )
    args = parser.parse_args(argv)

    xml_path = Path(args.file)
    try:
        xml_text = xml_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"settings_import could not read {xml_path}: {exc}", file=sys.stderr)
        return 2

    try:
        count = run_settings_import(xml_text, out_path=Path(args.out))
    except SettingsXmlError as exc:
        print(f"settings_import refused {xml_path}: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"settings_import could not write {args.out}: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {count} setting(s) to {args.out} — applied on the next restart that reads it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
