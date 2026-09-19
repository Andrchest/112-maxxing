"""Realtime fan-out adapters (HLD `40-realtime-protocol.md` §40.6).

Redis carries pub/sub only; PostgreSQL stays authoritative and the system survives a complete
Redis flush with no loss of simulation state (SPEC §31, D5).
"""

from __future__ import annotations

from app.infrastructure.realtime.redis_publisher import RedisEventPublisher, session_events_channel

__all__ = ["RedisEventPublisher", "session_events_channel"]
