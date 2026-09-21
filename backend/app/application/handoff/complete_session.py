"""Completing a session — `ACTIVE --complete--> COMPLETED`, with a real `total_events`.

A session is completed by finishing its **last** `role_chain` stage. There are two callers and
there will never be a third: `completeOperatorStage` on a chain of `[OPERATOR_112]` alone, and
`closeDdsIncident` on every chain that ends in DDS (E9-B). Both are stage commands that have
already fired their stage's terminal transition inside an open Unit of Work, so this is a
function over that transaction rather than a use case with its own — completing in a second
transaction would let a crash leave a terminal stage in an `ACTIVE` session.

`SESSION_COMPLETED.total_events` is why this exists. §10.13 types it `int` and means "how many
rows this session's log ended up with", including the `SESSION_COMPLETED` row itself. The
aggregate cannot know it (`next_seq_no` is deliberately not a field of `SimulationSession`) and
the number must not be guessed, so the count comes from the log: `seq_no` is dense and allocated
by the event store, so the highest `seq_no` in the transaction so far, plus the one this call is
about to allocate, *is* the row count.

Scoring is deliberately absent. `openapi.yaml` puts `SCORING_RULE_EVALUATED` in `closeDdsIncident`'s
`x-emits` and §10.14 owns the evaluators — TODO(E15). Emitting a `SCORING_*` event here with no
evaluator behind it would put a score in the audit log that no rule produced, so this function
emits `SESSION_COMPLETED` and nothing else, and the report stays unavailable until E15 lands.
"""

from __future__ import annotations

from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork
from app.domain.common.actors import ActorRef
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.session.session import SimulationSession

__all__ = ["SYSTEM_ACTOR", "complete_session"]

SYSTEM_ACTOR = ActorRef(actor_type=ActorType.SYSTEM)
"""`complete` is a `SYSTEM` trigger (§10.8): the engine ends the session, not the trainee."""


async def complete_session(
    uow: UnitOfWork,
    session: SimulationSession,
    *,
    clock: Clock,
    now_ms: int,
    last_seq_no: int,
    runtime: GuardRuntime,
) -> tuple[SimulationSession, list[DomainEvent]]:
    """Fire `complete`, persist the session and append `SESSION_COMPLETED` (§10.8).

    `last_seq_no` is the highest `seq_no` the caller's transaction has allocated so far, so
    `last_seq_no + 1` is the `seq_no` `SESSION_COMPLETED` will take and therefore the session's
    final row count. The caller commits; this function never does.
    """
    completed, events = session.complete(
        clock.now(),
        total_events=last_seq_no + 1,
        actor=SYSTEM_ACTOR,
        now_ms=now_ms,
        runtime=runtime,
    )
    await uow.sessions.save(completed)
    await uow.events.append(completed.id, events)
    return completed, events
