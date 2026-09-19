"""API layer.

FastAPI route handlers and app wiring: `api -> application -> domain` (D2). Handlers stay thin and
delegate to application services; business/domain logic never lives in a route function. May not
import `sqlalchemy`, `livekit`, `app.db`, or `app.inference` directly.
"""
