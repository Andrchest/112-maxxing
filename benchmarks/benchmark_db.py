#!/usr/bin/env python
"""Database write-rate benchmark: N×M appends through the product's `EventStore` (I7 E48).

ТЗ ¶164 (REQ-2141) «Скорость записи данных в БД не менее 100 операций в секунду».

What one run does: N concurrent writers (`--writers`, several values sweep one after another),
each appending M events (`--appends`) to its **own** session, one event per Unit of Work — the
production `SqlAlchemyUnitOfWork` over the production engine settings, so every append takes the
§20.8 `seq_no` row lock, runs the card-status flush-before-append (HLD 70 §70.3.5) over a started
session with an incident, inserts the row and commits (a WAL flush — PostgreSQL's default
`synchronous_commit`). That is the write every trainee command, tick and voice turn makes; an
append is counted when its commit has returned.

Reported per N: appends/s (all appends ÷ wall time from the first start to the last commit) and
the per-append latency p50/p95/p99/max, against the ¶164 target of 100/s. The sessions are raw
rows under a run-unique slug (`bench-db-<hex>`): one user, one scenario/version, N started
`simulation_sessions` with an incident each — nothing is deleted afterwards (the log is append-
only by trigger), so this runs against a **scratch** database only: the default own stack
(`_load_stack.py` without the backend, compose project `sim112loaddb` on loopback ports
35442/36389, `down -v` at the end) or an explicit `--database-url` the caller vouches is scratch.

The publisher is an in-memory recorder: Redis fan-out is not a database write and is measured by
`benchmark_load.py`'s WebSocket latency instead.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from _common import Envelope, aggregate, finish, not_run, parse_common_args
from _load_stack import OwnStack, StackConfig, StackError

BENCHMARK = "db"
#: A compose project and ports of its own, distinct from `benchmark_load.py`'s, so the two
#: benchmarks can never collide on one scratch stack.
DB_PROJECT = "sim112loaddb"
DB_PG_PORT = 35442
DB_REDIS_PORT = 36389
#: ТЗ ¶164 (REQ-2141): at least 100 database write operations per second.
TARGET_APPENDS_PER_S = 100.0


def _extra(parser: Any) -> None:
    parser.add_argument(
        "--writers",
        type=int,
        nargs="+",
        default=[1, 20, 100],
        metavar="N",
        help="concurrent writers (one session each); several values sweep",
    )
    parser.add_argument("--appends", type=int, default=100, metavar="M", help="appends per writer")
    parser.add_argument(
        "--database-url",
        default=None,
        help="a SCRATCH database (postgresql+asyncpg://...); default: start the own stack",
    )
    parser.add_argument("--project", default=DB_PROJECT)
    parser.add_argument("--pg-port", type=int, default=DB_PG_PORT)
    parser.add_argument("--redis-port", type=int, default=DB_REDIS_PORT)


def summarize(
    latencies_ms: Sequence[float], errors: Sequence[str], wall_s: float
) -> dict[str, Any]:
    """Appends/s, the latency percentiles and the ¶164 verdict of one writer count."""
    done = len(latencies_ms)
    per_s = done / wall_s if wall_s > 0 else None
    return {
        "appends": done,
        "errors": len(errors),
        "error_types": dict(Counter(errors)),
        "wall_s": round(wall_s, 3),
        "appends_per_s": per_s,
        "append_ms": aggregate(latencies_ms),
        "target_appends_per_s": TARGET_APPENDS_PER_S,
        "meets_target": None
        if per_s is None
        else bool(per_s >= TARGET_APPENDS_PER_S and not errors),
    }


async def _seed(engine: Any, writers: int) -> list[UUID]:
    """One user/scenario/version and `writers` started sessions with an incident each."""
    import sqlalchemy as sa

    tag = uuid4().hex[:8]
    async with engine.begin() as connection:
        user_id = (
            await connection.execute(
                sa.text(
                    "INSERT INTO users (username, password_hash, display_name_ru)"
                    " VALUES (:name, 'x', 'Нагрузка БД') RETURNING id"
                ),
                {"name": f"bench-db-{tag}"},
            )
        ).scalar_one()
        scenario_id = (
            await connection.execute(
                sa.text(
                    "INSERT INTO scenarios (slug, title_ru) VALUES (:slug, 'Нагрузка БД')"
                    " RETURNING id"
                ),
                {"slug": f"bench-db-{tag}"},
            )
        ).scalar_one()
        version_id = (
            await connection.execute(
                sa.text(
                    "INSERT INTO scenario_versions (scenario_id, version, schema_version, title,"
                    " deterministic_seed, role_chain, content, content_sha256)"
                    " VALUES (:scenario_id, 1, 1, 'bench', 'seed', ARRAY['DDS'],"
                    " CAST(:content AS jsonb), :sha) RETURNING id"
                ),
                {
                    "scenario_id": scenario_id,
                    "content": json.dumps({"version": 1}),
                    "sha": uuid4().hex,
                },
            )
        ).scalar_one()
        sessions: list[UUID] = []
        for _ in range(writers):
            session_id = (
                await connection.execute(
                    sa.text(
                        "INSERT INTO simulation_sessions (scenario_version_id, session_mode,"
                        " session_seed, created_by_user_id, state, started_at)"
                        " VALUES (:version_id, 'SINGLE_ROLE', 'seed', :user_id, 'ACTIVE', now())"
                        " RETURNING id"
                    ),
                    {"version_id": version_id, "user_id": user_id},
                )
            ).scalar_one()
            await connection.execute(
                sa.text(
                    "INSERT INTO incidents (session_id, scenario_version_id)"
                    " VALUES (:session_id, :version_id)"
                ),
                {"session_id": session_id, "version_id": version_id},
            )
            sessions.append(UUID(str(session_id)))
    return sessions


def _event(index: int) -> Any:
    """A card-field edit, the most frequent trainee event; `SYSTEM` actor (no user FK)."""
    from app.domain.common.actors import ActorRef
    from app.domain.enums import ActorType
    from app.domain.events.session_event import DomainEvent
    from app.domain.events.types import EventType

    return DomainEvent(
        event_type=EventType.CARD_FIELD_CHANGED,
        actor=ActorRef(actor_type=ActorType.SYSTEM),
        monotonic_offset_ms=index * 100,
        correlation_id=uuid4(),
        payload={"field_path": "address.house", "value": str(index), "revision": index},
    )


async def _writer(
    unit_of_work: Any, session_id: UUID, appends: int, latencies: list[float], errors: list[str]
) -> None:
    from app.domain.common.ids import SessionId

    for index in range(appends):
        started = time.perf_counter()
        try:
            async with unit_of_work() as uow:
                await uow.events.append(SessionId(session_id), [_event(index)])
                await uow.commit()
        except Exception as exc:
            errors.append(type(exc).__name__)
            continue
        latencies.append((time.perf_counter() - started) * 1000.0)


async def run(database_url: str, writer_counts: Sequence[int], appends: int) -> dict[str, Any]:
    """Every writer count against `database_url`; `{"by_writers": ..., "samples": [...]}`."""
    from app.application.testing.fakes import InMemoryEventPublisher
    from app.config.settings import Settings
    from app.db.session import create_session_factory
    from app.infrastructure.clock import SystemClock
    from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
    from sqlalchemy.ext.asyncio import create_async_engine

    defaults = Settings.model_fields
    # The API's own pool settings (`app.db.session.create_engine`), without building a whole
    # `Settings` (it would demand the JWT/LiveKit/LLM values this benchmark never uses).
    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
        pool_size=int(defaults["db_pool_size"].default),
        max_overflow=int(defaults["db_max_overflow"].default),
    )
    session_factory = create_session_factory(engine)
    clock = SystemClock()
    publisher = InMemoryEventPublisher()

    def unit_of_work() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, clock, publisher)

    by_writers: dict[str, Any] = {}
    samples: list[dict[str, Any]] = []
    try:
        for writers in writer_counts:
            sessions = await _seed(engine, writers)
            per_writer: list[list[float]] = [[] for _ in sessions]
            errors: list[str] = []
            started = time.perf_counter()
            await asyncio.gather(
                *(
                    _writer(unit_of_work, session_id, appends, per_writer[index], errors)
                    for index, session_id in enumerate(sessions)
                )
            )
            wall = time.perf_counter() - started
            latencies = [value for chunk in per_writer for value in chunk]
            by_writers[str(writers)] = summarize(latencies, errors, wall)
            samples.extend(
                {"writers": writers, "writer": index, "append_ms": round(value, 3)}
                for index, chunk in enumerate(per_writer)
                for value in chunk
            )
            publisher.published.clear()  # the recorder is not what is measured; keep it small
    finally:
        await engine.dispose()
    return {"by_writers": by_writers, "samples": samples}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_common_args(
        BENCHMARK, argv, extra=_extra, description="N×M EventStore appends (ТЗ ¶164)"
    )
    config: dict[str, Any] = {
        "writers": list(args.writers),
        "appends": args.appends,
        "stack": "external" if args.database_url else "own",
        "events_per_transaction": 1,
        "event_type": "CARD_FIELD_CHANGED",
        "tag": args.tag,
    }
    envelope = Envelope(benchmark=BENCHMARK, status="OK", profile=args.profile, config=config)
    envelope.note("one event per Unit of Work; synchronous_commit on (PostgreSQL default)")

    def measure(database_url: str) -> int:
        try:
            result = asyncio.run(run(database_url, args.writers, args.appends))
        except Exception as exc:
            return finish(
                not_run(BENCHMARK, args.profile, f"{type(exc).__name__}: {exc}", config=config),
                args.out,
            )
        envelope.samples = result["samples"]
        envelope.aggregates = {"by_writers": result["by_writers"]}
        failed = [n for n, entry in result["by_writers"].items() if entry["errors"]]
        if not envelope.samples:
            envelope.status = "FAILED"
            envelope.reason = "no append succeeded"
            envelope.aggregates = {}
        elif failed:
            envelope.status = "PARTIAL"
            envelope.reason = f"failed appends at N={', '.join(failed)}"
        return finish(envelope, args.out)

    if args.database_url:
        return measure(args.database_url)
    stack = OwnStack(
        StackConfig(
            project=args.project,
            pg_port=args.pg_port,
            redis_port=args.redis_port,
            with_backend=False,
        )
    )
    try:
        with stack:
            config["compose_project"] = args.project
            return measure(stack.database_url)
    except StackError as exc:
        return finish(not_run(BENCHMARK, args.profile, str(exc), config=config), args.out)


if __name__ == "__main__":
    sys.exit(main())
