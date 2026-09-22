"""`python -m app.cli <sub-command> [args...]` — dispatches to `preflight` / `purge_recordings`
(R7, R8). No sub-command, or an unknown one, prints the two names and exits 2."""

from __future__ import annotations

import sys

__all__ = ["main"]

_SUB_COMMANDS = ("preflight", "purge_recordings")


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _SUB_COMMANDS:
        given = argv[0] if argv else "<none>"
        print(
            f"usage: python -m app.cli {{{'|'.join(_SUB_COMMANDS)}}} [args...]\n"
            f"unknown sub-command: {given}",
            file=sys.stderr,
        )
        return 2

    name, rest = argv[0], argv[1:]
    if name == "preflight":
        from app.cli.preflight import main as preflight_main

        return preflight_main(rest)

    from app.cli.purge_recordings import main as purge_recordings_main

    return purge_recordings_main(rest)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
