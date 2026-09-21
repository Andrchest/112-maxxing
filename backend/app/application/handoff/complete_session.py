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

`complete_session` itself still emits `SESSION_COMPLETED` and nothing else: it runs inside the
caller's already-open Unit of Work (the stage transition's), and scoring must not share that
transaction (see `score_completed_session` below). E15-B wires scoring as a **second**, later Unit
of Work: `score_completed_session` is what `closeDdsIncident` (`app.api.routers.dds`) and
`completeOperatorStage` (`app.api.routers.operator`) call once their own commit has already
happened, exactly where each already calls `container.runner.release` "after the commit" (D7).

**Why two units of work (R2, CHANGE item 3).** R2's default reading is "scoring's event and rows
land in the same unit of work as `SESSION_COMPLETED`". Literally sharing that transaction would
mean a `ScoringEvidenceError` — raised by the pure `score()` call itself, before any scoring write
— rolls back everything in it, including `SESSION_COMPLETED`: the trainee's completed session
would vanish because a scoring rule could not produce its evidence, which is exactly the outcome
the manager ruling forbids ("must NOT lose the session"). D11/§10.14 say nothing about this
failure mode (checked; recon and the sections it quotes are silent), so this file takes the
ruling's explicit fallback: **completion commits first, scoring runs second**, in a fresh
transaction opened only after the first has already committed. A `ScoringEvidenceError` there is
logged at `ERROR` and swallowed *at this call site only* — the session stays `COMPLETED` with no
`score_results` rows, and a client calling `rescoreSession` later gets the same error as an
honest `500` (`app.application.scoring.rescore_session` does not catch it), which is what "a
scoring error surfaces as a 500 problem on rescore" means. **HLD gap**: this two-transaction
split and its exact failure behaviour are not written down anywhere in `00-decisions.md` or
`10-domain-model.md` §10.14; this docstring is the sentence the CHANGE item asked for.
"""

from __future__ import annotations

import logging

from app.application.ports.clock import Clock
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.scoring.score_session import score_session
from app.domain.common.actors import ActorRef
from app.domain.common.ids import SessionId
from app.domain.common.state_machine import GuardRuntime
from app.domain.enums import ActorType
from app.domain.events.session_event import DomainEvent
from app.domain.scoring.engine import ScoringEvidenceError
from app.domain.scoring.results import ScoreReport
from app.domain.session.session import SimulationSession

__all__ = ["SYSTEM_ACTOR", "complete_session", "score_completed_session"]

logger = logging.getLogger(__name__)

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


async def score_completed_session(
    unit_of_work: UnitOfWorkFactory, session_id: SessionId
) -> ScoreReport | None:
    """Score a just-`COMPLETED` session, in a transaction of its own (see the module docstring).

    Called only after the caller's own commit — `closeDdsIncident` / `completeOperatorStage`, both
    after `await tick`/`await container.runner.release` "after the commit" (D7) — never from
    inside `complete_session`, which is still running in the caller's open transaction at that
    point and must not risk it on a scoring failure.

    Returns the persisted `ScoreReport`, or `None` when `score()` could not produce one
    (`ScoringEvidenceError`, R3): the session stays `COMPLETED`, logged at `ERROR`, no
    `score_results` rows — the honest failure surfaces later, on `rescoreSession` (R9's sibling
    epic E16 report screen renders "not yet scored" for a `None`; `getReportExplanation` already
    refuses `409 REPORT_NOT_READY` before a report exists).
    """
    try:
        async with unit_of_work() as uow:
            report = await score_session(uow, session_id)
            await uow.commit()
            return report
    except ScoringEvidenceError:
        logger.error(
            "scoring session %s failed: a ScoreResult could not produce its required evidence; "
            "the session stays COMPLETED with no score_results rows (R3, CHANGE item 3)",
            session_id,
            exc_info=True,
        )
        return None
