"""Event log, transcript, audio and telemetry (HLD `20-db-schema.md` §20.6).

`session_events`, `transcript_segments`, `audio_segments`, `dialogue_turns`,
`recording_purge_audit`, `inference_metrics`.

`session_events` is the audit source; every other table in this module is a read model, a file
index or telemetry (D5).
"""

from __future__ import annotations

import sqlalchemy as sa

from app.db.base import (
    GEN_RANDOM_UUID,
    JSONB_T,
    NOW,
    TIMESTAMPTZ_T,
    UUID_T,
    Base,
    enum_check,
)
from app.domain.enums import ActorType
from app.domain.events.types import EventType

#: `transcript_segments.speaker` / `audio_segments.speaker` — the two voice-path speakers; the HLD
#: gives the members literally and `app.domain.enums` has no counterpart enum.
SPEAKERS: tuple[str, ...] = ("TRAINEE", "CALLER")
#: `inference_metrics.component` (SPEC §27); likewise literal in the HLD.
INFERENCE_COMPONENTS: tuple[str, ...] = ("ASR", "LLM_INTERPRETER", "LLM_GENERATOR", "TTS", "VAD")
#: `inference_metrics.status` — `50-voice-pipeline.md` §2.6's four `InferenceMetric.status`
#: values. §20.6's column list predates §2.6's type and does not name the column; see E12-A's
#: report under "HLD gaps" and migration `0004_inference_metric_status`.
METRIC_STATUSES: tuple[str, ...] = ("OK", "TIMEOUT", "ERROR", "CANCELLED")
#: `recording_purge_audit.reason` (SPEC §41, D9); likewise literal in the HLD.
PURGE_REASONS: tuple[str, ...] = ("RETENTION_WINDOW", "MANUAL_REQUEST", "ADMIN_DELETE")


class SessionEvent(Base):
    """`session_events` — the append-only audit source (HLD §20.6, SPEC §8, D5)."""

    __tablename__ = "session_events"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq_no = sa.Column(sa.BigInteger(), nullable=False)
    event_type = sa.Column(sa.Text(), nullable=False)
    timestamp_utc = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    monotonic_offset_ms = sa.Column(sa.Integer(), nullable=False)
    actor_type = sa.Column(sa.Text(), nullable=False)
    actor_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    correlation_id = sa.Column(UUID_T, nullable=True)
    payload = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))

    __table_args__ = (
        sa.UniqueConstraint("session_id", "seq_no", name="uq_session_events_session_seq"),
        sa.Index("ix_session_events_session_seq", "session_id", "seq_no"),
        sa.Index("ix_session_events_session_type", "session_id", "event_type"),
        sa.Index(
            "ix_session_events_correlation",
            "correlation_id",
            postgresql_where=sa.text("correlation_id IS NOT NULL"),
        ),
        sa.CheckConstraint(enum_check("actor_type", ActorType), name="actor_type"),
        sa.CheckConstraint(enum_check("event_type", EventType), name="event_type"),
    )


class AudioSegment(Base):
    """`audio_segments` — the recording file index (HLD §20.6, D9)."""

    __tablename__ = "audio_segments"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    speaker = sa.Column(sa.Text(), nullable=False)
    file_path = sa.Column(sa.Text(), nullable=True)
    format = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'wav'"))
    start_ms = sa.Column(sa.Integer(), nullable=False)
    end_ms = sa.Column(sa.Integer(), nullable=False)
    sample_rate = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("16000"))
    num_channels = sa.Column(sa.Integer(), nullable=False, server_default=sa.text("1"))
    byte_offset = sa.Column(sa.BigInteger(), nullable=False)
    byte_length = sa.Column(sa.BigInteger(), nullable=False)
    purged_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.Index("ix_audio_segments_session_start", "session_id", "start_ms"),
        sa.CheckConstraint(enum_check("speaker", SPEAKERS), name="speaker"),
        sa.CheckConstraint("end_ms >= start_ms", name="end_ms"),
    )


class TranscriptSegment(Base):
    """`transcript_segments` — materialized transcript (HLD §20.6, SPEC §19)."""

    __tablename__ = "transcript_segments"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    audio_segment_id = sa.Column(
        UUID_T, sa.ForeignKey("audio_segments.id", ondelete="SET NULL"), nullable=True
    )
    speaker = sa.Column(sa.Text(), nullable=False)
    start_ms = sa.Column(sa.Integer(), nullable=False)
    end_ms = sa.Column(sa.Integer(), nullable=False)
    text = sa.Column(sa.Text(), nullable=False)
    is_final = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("true"))
    confidence = sa.Column(sa.REAL(), nullable=True)
    asr_provider = sa.Column(sa.Text(), nullable=True)
    asr_model = sa.Column(sa.Text(), nullable=True)
    turn_index = sa.Column(sa.Integer(), nullable=True)

    __table_args__ = (
        sa.Index("ix_transcript_segments_session_start", "session_id", "start_ms"),
        sa.CheckConstraint(enum_check("speaker", SPEAKERS), name="speaker"),
        sa.CheckConstraint("end_ms >= start_ms", name="end_ms"),
    )


class DialogueTurn(Base):
    """`dialogue_turns` — materialized turn record (HLD §20.6, additive/ratified)."""

    __tablename__ = "dialogue_turns"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role_stage_id = sa.Column(
        UUID_T, sa.ForeignKey("role_stages.id", ondelete="CASCADE"), nullable=False
    )
    turn_index = sa.Column(sa.Integer(), nullable=False)
    user_speech_started_offset_ms = sa.Column(sa.Integer(), nullable=False)
    user_speech_ended_offset_ms = sa.Column(sa.Integer(), nullable=True)
    # Both FK names are given explicitly: the naming convention would generate identifiers longer
    # than PostgreSQL's 63-character limit for these two columns.
    operator_transcript_segment_id = sa.Column(
        UUID_T,
        sa.ForeignKey(
            "transcript_segments.id",
            ondelete="SET NULL",
            name="fk_dialogue_turns_operator_segment_transcript_segments",
        ),
        nullable=True,
    )
    caller_transcript_segment_id = sa.Column(
        UUID_T,
        sa.ForeignKey(
            "transcript_segments.id",
            ondelete="SET NULL",
            name="fk_dialogue_turns_caller_segment_transcript_segments",
        ),
        nullable=True,
    )
    interpretation = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    gate_output = sa.Column(JSONB_T, nullable=False, server_default=sa.text("'{}'::jsonb"))
    planned_text = sa.Column(sa.Text(), nullable=True)
    delivered_text = sa.Column(sa.Text(), nullable=True)
    interrupted = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    fallback_used = sa.Column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    speech_end_to_first_audio_ms = sa.Column(sa.Integer(), nullable=True)
    correlation_id = sa.Column(UUID_T, nullable=True)
    created_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)

    __table_args__ = (
        sa.UniqueConstraint("session_id", "turn_index", name="uq_dialogue_turns_session_index"),
        sa.Index("ix_dialogue_turns_session", "session_id", "turn_index"),
        sa.Index(
            "ix_dialogue_turns_correlation",
            "correlation_id",
            postgresql_where=sa.text("correlation_id IS NOT NULL"),
        ),
    )


class RecordingPurgeAudit(Base):
    """`recording_purge_audit` — retention audit (HLD §20.6, SPEC §41, D9)."""

    __tablename__ = "recording_purge_audit"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    purged_at = sa.Column(TIMESTAMPTZ_T, nullable=False, server_default=NOW)
    actor_type = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'SYSTEM'"))
    actor_user_id = sa.Column(UUID_T, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    audio_segment_id = sa.Column(
        UUID_T, sa.ForeignKey("audio_segments.id", ondelete="RESTRICT"), nullable=False
    )
    file_path_was = sa.Column(sa.Text(), nullable=False)
    bytes = sa.Column(sa.BigInteger(), nullable=False)
    retention_days = sa.Column(sa.Integer(), nullable=False)
    reason = sa.Column(sa.Text(), nullable=False)

    __table_args__ = (
        sa.Index("ix_recording_purge_audit_session", "session_id", "purged_at"),
        sa.CheckConstraint(enum_check("actor_type", ActorType), name="actor_type"),
        sa.CheckConstraint(enum_check("reason", PURGE_REASONS), name="reason"),
    )


class InferenceMetric(Base):
    """`inference_metrics` — latency telemetry, never read by scoring (HLD §20.6, SPEC §27)."""

    __tablename__ = "inference_metrics"

    id = sa.Column(UUID_T, primary_key=True, server_default=GEN_RANDOM_UUID)
    session_id = sa.Column(
        UUID_T, sa.ForeignKey("simulation_sessions.id", ondelete="CASCADE"), nullable=True
    )
    request_id = sa.Column(sa.Text(), nullable=False)
    component = sa.Column(sa.Text(), nullable=False)
    provider = sa.Column(sa.Text(), nullable=False)
    model = sa.Column(sa.Text(), nullable=False)
    model_version = sa.Column(sa.Text(), nullable=True)
    turn_index = sa.Column(sa.Integer(), nullable=True)
    input_tokens = sa.Column(sa.Integer(), nullable=True)
    input_duration_ms = sa.Column(sa.Integer(), nullable=True)
    output_tokens = sa.Column(sa.Integer(), nullable=True)
    output_audio_ms = sa.Column(sa.Integer(), nullable=True)
    started_at = sa.Column(TIMESTAMPTZ_T, nullable=False)
    first_output_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    finished_at = sa.Column(TIMESTAMPTZ_T, nullable=True)
    ttft_ms = sa.Column(sa.Integer(), nullable=True)
    total_latency_ms = sa.Column(sa.Integer(), nullable=True)
    tokens_per_second = sa.Column(sa.REAL(), nullable=True)
    realtime_factor = sa.Column(sa.REAL(), nullable=True)
    gpu_memory_mb = sa.Column(sa.Integer(), nullable=True)
    fallback_count = sa.Column(sa.SmallInteger(), nullable=False, server_default=sa.text("0"))
    retry_count = sa.Column(sa.SmallInteger(), nullable=False, server_default=sa.text("0"))
    status = sa.Column(sa.Text(), nullable=False, server_default=sa.text("'OK'"))
    error_kind = sa.Column(sa.Text(), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("request_id", name="uq_inference_metrics_request"),
        sa.Index("ix_inference_metrics_session_component", "session_id", "component", "started_at"),
        sa.CheckConstraint(enum_check("component", INFERENCE_COMPONENTS), name="component"),
        sa.CheckConstraint(enum_check("status", METRIC_STATUSES), name="status"),
    )
