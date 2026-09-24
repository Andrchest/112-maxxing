"""`python -m app.tools.set_sip_password` — set a user's own SIP password (I3 E6e, HLD
`80-telephony.md` §80.7, migration `0015_users_sip_ha1`, D27).

By default every trainee's softphone registers with the one deployment SIP password
(`SIM_SIP_PASSWORD`). This command gives one account its own: it stores
`users.sip_ha1 = MD5(username:realm:password)` — the Digest HA1 the gateway's registrar checks
REGISTER and INVITE against (via `GET /api/v1/telephony/sip-credentials/{username}`) — and never the
password itself. `--clear` sets the column back to `NULL`, so the deployment password applies again.

    python -m app.tools.set_sip_password --username trainee            # prompts twice
    SIM_SIP_USER_PASSWORD=... python -m app.tools.set_sip_password \\
        --username trainee --password-env SIM_SIP_USER_PASSWORD         # non-interactive
    python -m app.tools.set_sip_password --username trainee --clear

**The password is never a command-line argument** (it would land in the shell history and in
`ps`): it is read from the environment variable `--password-env` names, or from an interactive
prompt that does not echo. It is never printed, logged or written anywhere; the only output is the
username and what was done. The realm is `SIM_SIP_REALM` (default `sim112`); **changing the realm
later invalidates every stored HA1** — re-run this command for each account (the RUNBOOK says so).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import os
import sys
from collections.abc import Sequence

from app.config.settings import Settings, get_settings
from app.db.session import create_engine, create_session_factory
from app.infrastructure.clock import SystemClock
from app.infrastructure.persistence.unit_of_work import unit_of_work_factory

__all__ = ["main", "set_sip_ha1", "sip_ha1"]

_MIN_PASSWORD_CHARS = 8


class SipPasswordError(RuntimeError):
    """The password is missing, too short, or the two prompts disagree."""


def sip_ha1(username: str, realm: str, password: str) -> str:
    """RFC 2617 §3.2.2.2's `A1` digest: `MD5(username ":" realm ":" password)`, lowercase hex."""
    text = f"{username}:{realm}:{password}"
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


async def set_sip_ha1(settings: Settings, username: str, ha1: str | None) -> bool:
    """Write (or clear) `users.sip_ha1` for one username; `False` when there is no such account."""
    engine = create_engine(settings)
    try:
        unit_of_work = unit_of_work_factory(
            create_session_factory(engine), SystemClock(), _NullPublisher()
        )
        async with unit_of_work() as uow:
            found = await uow.users.set_sip_ha1(username, ha1)
            await uow.commit()
    finally:
        await engine.dispose()
    return found


class _NullPublisher:
    """An `EventPublisher` that publishes nothing: setting a credential appends no event."""

    async def publish(self, session_id: object, envelopes: object) -> None:
        """A no-op — there is nothing to fan out."""
        return None


def _read_password(password_env: str | None) -> str:
    if password_env:
        password = os.environ.get(password_env, "")
        if not password:
            raise SipPasswordError(f"{password_env} is unset or empty")
    else:
        password = getpass.getpass("New SIP password: ")
        if password != getpass.getpass("Repeat it: "):
            raise SipPasswordError("the two entries differ")
    if len(password) < _MIN_PASSWORD_CHARS:
        raise SipPasswordError(f"a SIP password needs at least {_MIN_PASSWORD_CHARS} characters")
    return password


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Prints the username and the action; never a password or a digest."""
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.set_sip_password",
        description="Set (or clear) one account's own SIP password (users.sip_ha1).",
    )
    parser.add_argument("--username", required=True, help="the account (users.username)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--password-env",
        default=None,
        metavar="NAME",
        help="read the password from this environment variable instead of a prompt",
    )
    group.add_argument(
        "--clear", action="store_true", help="drop the account's own SIP password (NULL)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()
    try:
        ha1 = (
            None
            if args.clear
            else sip_ha1(args.username, settings.sip_realm, _read_password(args.password_env))
        )
    except SipPasswordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not asyncio.run(set_sip_ha1(settings, args.username, ha1)):
        print(f"error: no account named {args.username!r}", file=sys.stderr)
        return 1
    action = "cleared (the deployment password applies)" if ha1 is None else "set"
    print(f"SIP password of {args.username}: {action}; realm {settings.sip_realm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
