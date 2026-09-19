"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(title="sim112-backend")

    @app.get("/api/v1/health/live")
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    # TODO(E7): scenarios + sessions endpoints, JWT auth, WebSocket realtime, role-filtered
    # snapshot.
    # TODO(E18): GET /api/v1/health/ready (postgres, redis, livekit, llm, asr, tts, vad
    # readiness).

    return app
