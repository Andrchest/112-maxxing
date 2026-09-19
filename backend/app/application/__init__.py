"""Application layer.

Use-case services, ports (`typing.Protocol`), the Unit of Work, the simulation runner and the
dialogue turn pipeline. May depend on `app.domain` only among first-party layers: it may not import
`app.infrastructure`, `app.inference` adapters, `app.api`, `app.db`, or any vendor SDK (fastapi,
starlette, sqlalchemy, alembic, redis, livekit, httpx, asyncpg). Enforced by
`backend/tools/check_imports.py` (D2).
"""
