"""`MetricsRecorder` adapters (HLD `50-voice-pipeline.md` §2.6, SPEC §27).

`PgMetricsRecorder` is the one that writes `inference_metrics`. E11's `NullMetricsRecorder` stays
in the port module as the in-memory recorder the unit tests use.
"""

from __future__ import annotations

from app.infrastructure.metrics.pg_metrics_recorder import PgMetricsRecorder

__all__ = ["PgMetricsRecorder"]
