"""Domain layer.

Pure Python + Pydantic v2 only: no FastAPI, Starlette, SQLAlchemy, Redis, LiveKit or httpx
imports, no I/O, no wall clock (`time` is forbidden — a `Clock` port is injected instead), and no
module-level `random` state (`from random import Random` is the only allowed form; seeded
instances are passed in or derived). May not import `app.application`, `app.api`,
`app.infrastructure`, `app.inference` or `app.db`. Enforced by `backend/tools/check_imports.py`
(D2).
"""
