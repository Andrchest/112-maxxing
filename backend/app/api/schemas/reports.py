"""`reports` schemas — the `SessionReport` envelope, `ScoreReportView`, `RescoreResult`,
`ReportReleaseView` and the SPEC §27 telemetry page (`openapi.yaml`, SPEC §27-§29, D11).

Property names are copied **literally** from the contract (`backend/tests/api/test_contract.py`).

`ScoreResultView` needs `name_ru` / `description_ru`, which are not on the domain `ScoreResult` —
only `ScoringRule` (the scenario's own rule catalog) carries them, so every mapper here that builds
one takes a `rules_by_id: Mapping[str, ScoringRule]` alongside the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.dds import StatusUpdateViewSchema, status_update_schema
from app.api.schemas.handoff import HandoffSnapshotViewSchema, handoff_snapshot_schema
from app.api.schemas.operator import (
    FactValueSchema,
    OperatorCardViewSchema,
    operator_card_schema,
)
from app.api.schemas.sessions import SessionDetailSchema, session_detail_schema
from app.application.handoff.create_handoff import handoff_snapshot_view
from app.application.ports.inference_metric_repository import (
    InferenceComponent,
    StoredInferenceMetric,
)
from app.application.ports.report_explanation_repository import (
    ExplanationAudience,
    StoredReportExplanation,
)
from app.application.ports.session_repository import ReportRelease
from app.application.reports.assemble_report import SessionReportView
from app.application.reports.dds_decisions import DdsDecision
from app.application.reports.list_inference_metrics import InferenceMetricsPage
from app.application.reports.resource_timeline import ResourceTimelineEntry
from app.application.reports.timeline import TimelineEntry
from app.application.reports.timing_metrics import TimingMetrics
from app.application.reports.transcript import AudioSegmentRef, TranscriptEntry, ViewSpeaker
from app.application.reports.truth_vs_card import TruthVsCardEntry, Verdict
from app.application.scoring.rescore_session import RescoreOutcome
from app.domain.common.ids import SessionId
from app.domain.enums import (
    ActorType,
    ClosureReason,
    EvaluatorType,
    ResourceStatus,
    ScoringCategory,
    ServiceType,
)
from app.domain.events.types import EventType
from app.domain.scoring.results import ScoreCategoryTotal, ScoreEvidence, ScoreReport, ScoreResult
from app.domain.scoring.rules import ScoringRule

__all__ = [
    "AudioSegmentRefSchema",
    "DdsDecisionViewSchema",
    "DispatchEventSchema",
    "GenerateExplanationRequestSchema",
    "InferenceMetricViewSchema",
    "InferenceMetricsPageSchema",
    "ReportExplanationSchema",
    "ReportReleaseViewSchema",
    "RescoreDifferenceSchema",
    "RescoreRequestSchema",
    "RescoreResultSchema",
    "ResourceTimelineEntryViewSchema",
    "ScoreCategoryTotalViewSchema",
    "ScoreEvidenceViewSchema",
    "ScoreReportViewSchema",
    "ScoreResultViewSchema",
    "SessionReportSchema",
    "TimelineEntryViewSchema",
    "TimingMetricsViewSchema",
    "TranscriptSegmentViewSchema",
    "TruthVsCardDiffEntrySchema",
    "audio_segment_ref_schema",
    "dds_decision_schema",
    "inference_metric_schema",
    "inference_metrics_page_schema",
    "report_explanation_schema",
    "report_release_schema",
    "rescore_result_schema",
    "resource_timeline_entry_schema",
    "score_report_view_schema",
    "score_result_view_schema",
    "session_report_schema",
    "timeline_entry_schema",
    "timing_metrics_schema",
    "transcript_segment_schema",
    "truth_vs_card_entry_schema",
]


class RescoreRequestSchema(ApiModel):
    """`openapi.yaml`'s `RescoreRequest` — the optional body of `rescoreSession`."""

    persist: bool = Field(default=False)


class ScoreEvidenceViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreEvidenceView`."""

    event_id: UUID | None
    card_revision_id: UUID | None
    snapshot_id: UUID | None
    seq_no: int | None
    note_ru: str


class ScoreResultViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreResultView`."""

    rule_id: str
    name_ru: str
    description_ru: str
    evaluator_type: EvaluatorType
    category: ScoringCategory
    points_awarded: float
    max_points: float
    passed: bool
    critical_failure: bool
    evidence: list[ScoreEvidenceViewSchema]


class ScoreCategoryTotalViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreCategoryTotalView`."""

    category: ScoringCategory
    points_awarded: float
    max_points: float


class ScoreReportViewSchema(ApiModel):
    """`openapi.yaml`'s `ScoreReportView`."""

    scenario_version_id: UUID
    session_id: UUID
    total_points: float
    total_max_points: float
    by_category: list[ScoreCategoryTotalViewSchema]
    critical_errors: list[ScoreResultViewSchema]
    results: list[ScoreResultViewSchema]
    computed_from_event_count: int
    checksum: str


class RescoreDifferenceSchema(ApiModel):
    """One item of `openapi.yaml`'s `RescoreResult.differences`."""

    rule_id: str
    stored_points: float | None
    recomputed_points: float


class RescoreResultSchema(ApiModel):
    """`openapi.yaml`'s `RescoreResult`."""

    session_id: UUID
    identical_to_stored: bool
    recomputed: ScoreReportViewSchema
    stored_checksum: str | None
    recomputed_checksum: str
    differences: list[RescoreDifferenceSchema]
    persisted: bool


def score_evidence_view_schema(evidence: ScoreEvidence) -> ScoreEvidenceViewSchema:
    """`ScoreEvidence` -> the wire model."""
    return ScoreEvidenceViewSchema(
        event_id=UUID(str(evidence.event_id)) if evidence.event_id is not None else None,
        card_revision_id=(
            UUID(str(evidence.card_revision_id)) if evidence.card_revision_id is not None else None
        ),
        snapshot_id=UUID(str(evidence.snapshot_id)) if evidence.snapshot_id is not None else None,
        seq_no=evidence.seq_no,
        note_ru=evidence.note_ru,
    )


def score_result_view_schema(
    result: ScoreResult, rules_by_id: Mapping[str, ScoringRule]
) -> ScoreResultViewSchema:
    """`ScoreResult` + its rule's `name_ru`/`description_ru` -> the wire model."""
    rule = rules_by_id[result.rule_id]
    return ScoreResultViewSchema(
        rule_id=result.rule_id,
        name_ru=rule.name_ru,
        description_ru=rule.description_ru,
        evaluator_type=result.evaluator_type,
        category=result.category,
        points_awarded=result.points_awarded,
        max_points=result.max_points,
        passed=result.passed,
        critical_failure=result.critical_failure,
        evidence=[score_evidence_view_schema(evidence) for evidence in result.evidence],
    )


def score_category_total_view_schema(total: ScoreCategoryTotal) -> ScoreCategoryTotalViewSchema:
    """`ScoreCategoryTotal` -> the wire model."""
    return ScoreCategoryTotalViewSchema(
        category=total.category, points_awarded=total.points_awarded, max_points=total.max_points
    )


def score_report_view_schema(
    report: ScoreReport, rules_by_id: Mapping[str, ScoringRule], *, checksum: str
) -> ScoreReportViewSchema:
    """`ScoreReport` -> the wire model. `checksum` is computed by the caller (`report_checksum`,
    a pure domain function `app.api.schemas` never calls on its own)."""
    return ScoreReportViewSchema(
        scenario_version_id=UUID(str(report.scenario_version_id)),
        session_id=UUID(str(report.session_id)),
        total_points=report.total_points,
        total_max_points=report.total_max_points,
        by_category=[score_category_total_view_schema(total) for total in report.by_category],
        critical_errors=[
            score_result_view_schema(result, rules_by_id) for result in report.critical_errors
        ],
        results=[score_result_view_schema(result, rules_by_id) for result in report.results],
        computed_from_event_count=report.computed_from_event_count,
        checksum=checksum,
    )


def rescore_result_schema(outcome: RescoreOutcome) -> RescoreResultSchema:
    """`RescoreOutcome` -> the wire model."""
    rules_by_id = {rule.rule_id: rule for rule in outcome.scoring_rules}
    return RescoreResultSchema(
        session_id=UUID(str(outcome.session_id)),
        identical_to_stored=outcome.identical_to_stored,
        recomputed=score_report_view_schema(
            outcome.recomputed, rules_by_id, checksum=outcome.recomputed_checksum
        ),
        stored_checksum=outcome.stored_checksum,
        recomputed_checksum=outcome.recomputed_checksum,
        differences=[
            RescoreDifferenceSchema(
                rule_id=difference.rule_id,
                stored_points=difference.stored_points,
                recomputed_points=difference.recomputed_points,
            )
            for difference in outcome.differences
        ],
        persisted=outcome.persisted,
    )


# ---------------------------------------------------------------------------------------------
# E16 — the post-session report, release, audio and telemetry (`openapi.yaml`, SPEC §29, §27)
# ---------------------------------------------------------------------------------------------


class ReportReleaseViewSchema(ApiModel):
    """`openapi.yaml`'s `ReportReleaseView` — what `releaseReportToTrainee` answers with."""

    session_id: UUID
    released: bool
    released_at: datetime | None
    released_by_user_id: UUID | None


class TranscriptSegmentViewSchema(ApiModel):
    """`openapi.yaml`'s `TranscriptSegmentView` (SPEC §19's field list).

    `speaker` is the contract's `OPERATOR | CALLER`; the database stores `TRAINEE | CALLER` and
    `app.application.reports.transcript` performs the rename (E16 R5).
    """

    id: UUID
    speaker: ViewSpeaker
    start_ms: int
    end_ms: int
    text: str
    is_final: bool
    confidence: float | None
    asr_provider: str | None
    asr_model: str | None
    audio_segment_id: UUID | None
    turn_index: int | None


class AudioSegmentRefSchema(ApiModel):
    """`openapi.yaml`'s `AudioSegmentRef` — fetch each with `getAudioSegment`."""

    audio_segment_id: UUID
    speaker: ViewSpeaker
    start_ms: int
    end_ms: int
    sample_rate: int
    purged: bool


class TimelineEntryViewSchema(ApiModel):
    """`openapi.yaml`'s `TimelineEntryView` — one projected `session_events` row."""

    seq_no: int = Field(ge=1)
    event_type: EventType
    monotonic_offset_ms: int
    timestamp_utc: datetime
    actor_type: ActorType
    actor_id: UUID | None
    summary_ru: str
    payload: dict[str, Any]


class DispatchEventSchema(ApiModel):
    """One item of `openapi.yaml`'s `DdsDecisionView.dispatch_events`."""

    at_offset_ms: int
    resource_ids: list[UUID]
    callsigns: list[str]
    is_additional: bool
    note_ru: str | None = None


class DdsDecisionViewSchema(ApiModel):
    """`openapi.yaml`'s `DdsDecisionView` — one leg of the work item, as decided."""

    assignment_id: UUID
    service_type: ServiceType
    acknowledged_at_offset_ms: int | None
    dispatch_events: list[DispatchEventSchema]
    status_updates: list[StatusUpdateViewSchema]
    closure_reason: ClosureReason | None
    closed_at_offset_ms: int | None
    comment_ru: str | None = None


class ResourceTimelineEntryViewSchema(ApiModel):
    """`openapi.yaml`'s `ResourceTimelineEntryView` — one `RESOURCE_STATUS_CHANGED` step."""

    resource_id: UUID
    callsign: str
    previous_status: ResourceStatus | None
    new_status: ResourceStatus
    trigger: str
    at_offset_ms: int


class TimingMetricsViewSchema(ApiModel):
    """`openapi.yaml`'s `TimingMetricsView`.

    Every percentile is nullable because SPEC §27 forbids faking a benchmark value: a metric with
    no measurement is `null`, never `0`.
    """

    turn_count: int = Field(ge=0)
    speech_end_to_first_audio_ms_p50: float | None
    speech_end_to_first_audio_ms_p95: float | None
    asr_latency_ms_p50: float | None
    llm_ttft_ms_p50: float | None
    tts_first_audio_ms_p50: float | None
    barge_in_cutoff_ms_p95: float | None
    fallback_count: int = Field(ge=0)


class TruthVsCardDiffEntrySchema(ApiModel):
    """`openapi.yaml`'s `TruthVsCardDiffEntry` — the one place `WorldTruth` is shown (D11)."""

    field_path: str
    label_ru: str
    world_fact_id: str | None
    world_value: FactValueSchema
    card_value: FactValueSchema
    verdict: Verdict


class SessionReportSchema(ApiModel):
    """`openapi.yaml`'s `SessionReport` — every SPEC §29 item, in SPEC's own order."""

    session_id: UUID
    session: SessionDetailSchema
    score_report: ScoreReportViewSchema
    timeline: list[TimelineEntryViewSchema]
    transcript: list[TranscriptSegmentViewSchema]
    audio_segments: list[AudioSegmentRefSchema]
    final_card: OperatorCardViewSchema
    truth_vs_card_diff: list[TruthVsCardDiffEntrySchema]
    handoff: HandoffSnapshotViewSchema | None
    dds_decisions: list[DdsDecisionViewSchema]
    resource_timeline: list[ResourceTimelineEntryViewSchema]
    timing_metrics: TimingMetricsViewSchema
    explanation_available: bool
    released: bool


class InferenceMetricViewSchema(ApiModel):
    """`openapi.yaml`'s `InferenceMetricView` — one `inference_metrics` row (SPEC §27)."""

    id: UUID
    session_id: UUID | None
    request_id: str
    component: InferenceComponent
    provider: str
    model: str
    model_version: str | None
    turn_index: int | None
    input_tokens: int | None
    input_duration_ms: int | None
    output_tokens: int | None
    output_audio_ms: int | None
    started_at: datetime
    first_output_at: datetime | None
    finished_at: datetime | None
    ttft_ms: int | None
    total_latency_ms: int | None
    tokens_per_second: float | None
    realtime_factor: float | None
    gpu_memory_mb: int | None
    fallback_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)


class InferenceMetricsPageSchema(ApiModel):
    """`openapi.yaml`'s `InferenceMetricsPage`."""

    items: list[InferenceMetricViewSchema]
    total: int = Field(ge=0)
    timing_metrics: TimingMetricsViewSchema


# -- mappers ----------------------------------------------------------------------------------


def report_release_schema(
    session_id: SessionId, release: ReportRelease | None
) -> ReportReleaseViewSchema:
    """`ReportRelease | None` -> the wire model; absence *is* `released: false`."""
    return ReportReleaseViewSchema(
        session_id=UUID(str(session_id)),
        released=release is not None,
        released_at=None if release is None else release.released_at,
        released_by_user_id=(None if release is None else UUID(str(release.released_by_user_id))),
    )


def timeline_entry_schema(entry: TimelineEntry) -> TimelineEntryViewSchema:
    """`TimelineEntry` -> the wire model."""
    return TimelineEntryViewSchema(
        seq_no=entry.seq_no,
        event_type=entry.event_type,
        monotonic_offset_ms=entry.monotonic_offset_ms,
        timestamp_utc=entry.timestamp_utc,
        actor_type=entry.actor_type,
        actor_id=entry.actor_id,
        summary_ru=entry.summary_ru,
        # Already JSON-safe: `session_events.payload` is `jsonb`, and the event store writes it
        # through `json_safe_payload` at the one `DomainEvent` -> row boundary (§20.8).
        payload=dict(entry.payload),
    )


def transcript_segment_schema(entry: TranscriptEntry) -> TranscriptSegmentViewSchema:
    """`TranscriptEntry` -> the wire model."""
    return TranscriptSegmentViewSchema(
        id=entry.id,
        speaker=entry.speaker,
        start_ms=entry.start_ms,
        end_ms=entry.end_ms,
        text=entry.text,
        is_final=entry.is_final,
        confidence=entry.confidence,
        asr_provider=entry.asr_provider,
        asr_model=entry.asr_model,
        audio_segment_id=entry.audio_segment_id,
        turn_index=entry.turn_index,
    )


def audio_segment_ref_schema(ref: AudioSegmentRef) -> AudioSegmentRefSchema:
    """`AudioSegmentRef` -> the wire model."""
    return AudioSegmentRefSchema(
        audio_segment_id=ref.audio_segment_id,
        speaker=ref.speaker,
        start_ms=ref.start_ms,
        end_ms=ref.end_ms,
        sample_rate=ref.sample_rate,
        purged=ref.purged,
    )


def dds_decision_schema(decision: DdsDecision) -> DdsDecisionViewSchema:
    """`DdsDecision` -> the wire model."""
    return DdsDecisionViewSchema(
        assignment_id=decision.assignment_id,
        service_type=decision.service_type,
        acknowledged_at_offset_ms=decision.acknowledged_at_offset_ms,
        dispatch_events=[
            DispatchEventSchema(
                at_offset_ms=dispatch.at_offset_ms,
                resource_ids=list(dispatch.resource_ids),
                callsigns=list(dispatch.callsigns),
                is_additional=dispatch.is_additional,
                note_ru=dispatch.note_ru,
            )
            for dispatch in decision.dispatch_events
        ],
        status_updates=[status_update_schema(update) for update in decision.status_updates],
        closure_reason=decision.closure_reason,
        closed_at_offset_ms=decision.closed_at_offset_ms,
        comment_ru=decision.comment_ru,
    )


def resource_timeline_entry_schema(
    entry: ResourceTimelineEntry,
) -> ResourceTimelineEntryViewSchema:
    """`ResourceTimelineEntry` -> the wire model."""
    return ResourceTimelineEntryViewSchema(
        resource_id=entry.resource_id,
        callsign=entry.callsign,
        previous_status=entry.previous_status,
        new_status=entry.new_status,
        trigger=entry.trigger,
        at_offset_ms=entry.at_offset_ms,
    )


def timing_metrics_schema(metrics: TimingMetrics) -> TimingMetricsViewSchema:
    """`TimingMetrics` -> the wire model."""
    return TimingMetricsViewSchema(
        turn_count=metrics.turn_count,
        speech_end_to_first_audio_ms_p50=metrics.speech_end_to_first_audio_ms_p50,
        speech_end_to_first_audio_ms_p95=metrics.speech_end_to_first_audio_ms_p95,
        asr_latency_ms_p50=metrics.asr_latency_ms_p50,
        llm_ttft_ms_p50=metrics.llm_ttft_ms_p50,
        tts_first_audio_ms_p50=metrics.tts_first_audio_ms_p50,
        barge_in_cutoff_ms_p95=metrics.barge_in_cutoff_ms_p95,
        fallback_count=metrics.fallback_count,
    )


def truth_vs_card_entry_schema(entry: TruthVsCardEntry) -> TruthVsCardDiffEntrySchema:
    """`TruthVsCardEntry` -> the wire model."""
    return TruthVsCardDiffEntrySchema(
        field_path=entry.field_path,
        label_ru=entry.label_ru,
        world_fact_id=entry.world_fact_id,
        world_value=entry.world_value,
        card_value=entry.card_value,
        verdict=entry.verdict,
    )


def session_report_schema(view: SessionReportView) -> SessionReportSchema:
    """`SessionReportView` -> the wire model — every §29 item, none of them omitted."""
    rules_by_id = {rule.rule_id: rule for rule in view.scoring_rules}
    final_card = view.final_card
    return SessionReportSchema(
        session_id=UUID(str(view.session_id)),
        session=session_detail_schema(view.session),
        score_report=score_report_view_schema(
            view.score_report, rules_by_id, checksum=view.checksum
        ),
        timeline=[timeline_entry_schema(entry) for entry in view.timeline],
        transcript=[transcript_segment_schema(entry) for entry in view.transcript],
        audio_segments=[audio_segment_ref_schema(ref) for ref in view.audio_segments],
        final_card=operator_card_schema(final_card),
        truth_vs_card_diff=[truth_vs_card_entry_schema(entry) for entry in view.truth_vs_card_diff],
        handoff=(
            None
            if view.handoff is None
            else handoff_snapshot_schema(handoff_snapshot_view(view.handoff))
        ),
        dds_decisions=[dds_decision_schema(decision) for decision in view.dds_decisions],
        resource_timeline=[
            resource_timeline_entry_schema(entry) for entry in view.resource_timeline
        ],
        timing_metrics=timing_metrics_schema(view.timing_metrics),
        explanation_available=view.explanation_available,
        released=view.released,
    )


def inference_metric_schema(metric: StoredInferenceMetric) -> InferenceMetricViewSchema:
    """`StoredInferenceMetric` -> the wire model (every SPEC §27 field)."""
    return InferenceMetricViewSchema(
        id=metric.id,
        session_id=None if metric.session_id is None else UUID(str(metric.session_id)),
        request_id=metric.request_id,
        component=metric.component,
        provider=metric.provider,
        model=metric.model,
        model_version=metric.model_version,
        turn_index=metric.turn_index,
        input_tokens=metric.input_tokens,
        input_duration_ms=metric.input_duration_ms,
        output_tokens=metric.output_tokens,
        output_audio_ms=metric.output_audio_ms,
        started_at=metric.started_at,
        first_output_at=metric.first_output_at,
        finished_at=metric.finished_at,
        ttft_ms=metric.ttft_ms,
        total_latency_ms=metric.total_latency_ms,
        tokens_per_second=metric.tokens_per_second,
        realtime_factor=metric.realtime_factor,
        gpu_memory_mb=metric.gpu_memory_mb,
        fallback_count=metric.fallback_count,
        retry_count=metric.retry_count,
    )


def inference_metrics_page_schema(page: InferenceMetricsPage) -> InferenceMetricsPageSchema:
    """`InferenceMetricsPage` -> the wire model."""
    return InferenceMetricsPageSchema(
        items=[inference_metric_schema(metric) for metric in page.items],
        total=page.total,
        timing_metrics=timing_metrics_schema(page.timing_metrics),
    )


# ---------------------------------------------------------------------------------------------
# E16-B — the optional LLM explanation of an already-computed score report (SPEC §2, §29, D11)
# ---------------------------------------------------------------------------------------------


class GenerateExplanationRequestSchema(ApiModel):
    """`openapi.yaml`'s `GenerateExplanationRequest` — the optional body of
    `generateReportExplanation`."""

    regenerate: bool = Field(default=False)
    audience: ExplanationAudience = Field(default="TRAINEE")


class ReportExplanationSchema(ApiModel):
    """`openapi.yaml`'s `ReportExplanation`. `score_report_checksum` is echoed, never
    recomputed here: a client compares it against `ScoreReportView.checksum` to see whether the
    explanation is stale (SPEC §2)."""

    session_id: UUID
    audience: ExplanationAudience
    text_ru: str
    generated_at: datetime
    llm_provider: str
    llm_model: str
    score_report_checksum: str


def report_explanation_schema(explanation: StoredReportExplanation) -> ReportExplanationSchema:
    """`StoredReportExplanation` -> the wire model."""
    return ReportExplanationSchema(
        session_id=UUID(str(explanation.session_id)),
        audience=explanation.audience,
        text_ru=explanation.text_ru,
        generated_at=explanation.generated_at,
        llm_provider=explanation.llm_provider,
        llm_model=explanation.llm_model,
        score_report_checksum=explanation.score_report_checksum,
    )
