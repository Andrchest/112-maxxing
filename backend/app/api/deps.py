"""FastAPI dependencies that reach the `Container` (D2, D8).

The container is put on `app.state` by `create_app` and read back here. Nothing in this module
constructs an adapter — that is `app.api.container`'s sole privilege — so a dependency is always a
lookup, never a build, and a test that passed a container with fakes has every endpoint using them
without patching anything.

`tick_after_command` is the seam E7-B needs. D7 says the runner ticks "every `SIM_TICK_MS` and
immediately after each command"; a command endpoint therefore awaits this dependency's callable
**after** its use case has committed, so the world engine sees the command's effects at once
rather than up to one tick later.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.container import Container
from app.application.simulation.tick_session import TickResult
from app.domain.common.ids import SessionId

__all__ = [
    "ContainerDep",
    "TickAfterCommandDep",
    "get_container",
    "tick_after_command",
]


def get_container(request: Request) -> Container:
    """The application's `Container`, put on `app.state` by `create_app`."""
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - create_app always sets it
        raise RuntimeError("the application has no container; build it with create_app()")
    assert isinstance(container, Container)
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def tick_after_command(
    container: ContainerDep,
) -> Callable[[SessionId], Awaitable[TickResult]]:
    """D7's "and immediately after each command" — for E7-B's command endpoints.

    Usage in a command endpoint::

        session = await use_case(session_id, actor)      # commits
        await tick(session_id)                           # the world sees it now

    It deliberately does **not** require the runner lock: a command is already serialised against
    the tick loop by the session row lock of §20.8, and waiting for a lock another instance holds
    would make the command's own effects invisible until that instance's next tick
    (`SimulationRunner.tick_now`).
    """

    async def tick(session_id: SessionId) -> TickResult:
        return await container.runner.tick_now(session_id)

    return tick


TickAfterCommandDep = Annotated[
    Callable[[SessionId], Awaitable[TickResult]], Depends(tick_after_command)
]
