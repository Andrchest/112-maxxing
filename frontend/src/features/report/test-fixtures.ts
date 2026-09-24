// Shared fixtures for `features/report`'s co-located tests, mirroring `features/dds/test-
// fixtures.ts`. Every factory returns a minimal-but-valid instance of a generated schema type,
// overridable per test.
import type {
  ActorType,
  AudioSegmentRef,
  DdsDecisionView,
  EventType,
  HandoffSnapshotView,
  InferenceMetricView,
  InferenceMetricsPage,
  OperatorCardView,
  ReportExplanation,
  ResourceTimelineEntryView,
  ScoreCategoryTotalView,
  ScoreEvidenceView,
  ScoreReportView,
  ScoreResultView,
  SessionDetail,
  SessionReport,
  TimelineEntryView,
  TimingMetricsView,
  TranscriptSegmentView,
  TruthVsCardDiffEntry,
} from '@/shared/api';

export function makeScoreEvidence(overrides: Partial<ScoreEvidenceView> = {}): ScoreEvidenceView {
  return {
    event_id: 'event-1',
    card_revision_id: null,
    snapshot_id: null,
    seq_no: 3,
    note_ru: 'Поле заполнено верно',
    ...overrides,
  };
}

export function makeScoreResult(overrides: Partial<ScoreResultView> = {}): ScoreResultView {
  return {
    rule_id: 'rule-1',
    name_ru: 'Адрес указан верно',
    description_ru: 'Адрес происшествия совпадает с реальным адресом',
    evaluator_type: 'CARD_FIELD_CORRECT',
    category: 'CARD_QUALITY',
    points_awarded: 5,
    max_points: 5,
    passed: true,
    critical_failure: false,
    evidence: [makeScoreEvidence()],
    ...overrides,
  };
}

export function makeScoreCategoryTotal(overrides: Partial<ScoreCategoryTotalView> = {}): ScoreCategoryTotalView {
  return {
    category: 'CARD_QUALITY',
    points_awarded: 5,
    max_points: 5,
    ...overrides,
  };
}

export function makeScoreReport(overrides: Partial<ScoreReportView> = {}): ScoreReportView {
  return {
    scenario_version_id: 'scenario-version-1',
    session_id: 'session-1',
    total_points: 42,
    total_max_points: 60,
    by_category: [makeScoreCategoryTotal()],
    critical_errors: [],
    results: [makeScoreResult()],
    computed_from_event_count: 120,
    checksum: 'checksum-abc',
    ...overrides,
  };
}

export function makeTranscriptSegment(overrides: Partial<TranscriptSegmentView> = {}): TranscriptSegmentView {
  return {
    id: 'transcript-1',
    speaker: 'CALLER',
    start_ms: 1000,
    end_ms: 3000,
    text: 'У нас пожар на кухне.',
    is_final: true,
    confidence: 0.95,
    asr_provider: 'giga-am',
    asr_model: 'v3_e2e_ctc',
    audio_segment_id: 'audio-1',
    turn_index: 0,
    ...overrides,
  };
}

export function makeAudioSegment(overrides: Partial<AudioSegmentRef> = {}): AudioSegmentRef {
  return {
    audio_segment_id: 'audio-1',
    speaker: 'CALLER',
    start_ms: 1000,
    end_ms: 3000,
    sample_rate: 16000,
    purged: false,
    ...overrides,
  };
}

export function makeTimelineEntry(overrides: Partial<TimelineEntryView> = {}): TimelineEntryView {
  return {
    seq_no: 3,
    event_type: 'CARD_FIELD_CHANGED' as EventType,
    monotonic_offset_ms: 1500,
    timestamp_utc: '2026-09-21T00:00:03Z',
    actor_type: 'TRAINEE' as ActorType,
    actor_id: 'user-1',
    summary_ru: 'Стажёр изменил поле карточки «Адрес»',
    payload: {},
    ...overrides,
  };
}

export function makeDdsDecision(overrides: Partial<DdsDecisionView> = {}): DdsDecisionView {
  return {
    assignment_id: 'assignment-1',
    service_type: 'FIRE_RESCUE',
    acknowledged_at_offset_ms: 2000,
    dispatch_events: [{ at_offset_ms: 3000, resource_ids: ['resource-1'], callsigns: ['А-101'], is_additional: false }],
    status_updates: [],
    closure_reason: 'RESOLVED',
    closed_at_offset_ms: 9000,
    ...overrides,
  };
}

export function makeResourceTimelineEntry(overrides: Partial<ResourceTimelineEntryView> = {}): ResourceTimelineEntryView {
  return {
    resource_id: 'resource-1',
    callsign: 'А-101',
    previous_status: 'SELECTED',
    new_status: 'DISPATCHED',
    trigger: 'dispatch',
    at_offset_ms: 3000,
    ...overrides,
  };
}

export function makeTimingMetrics(overrides: Partial<TimingMetricsView> = {}): TimingMetricsView {
  return {
    turn_count: 8,
    speech_end_to_first_audio_ms_p50: 900,
    speech_end_to_first_audio_ms_p95: 1800,
    asr_latency_ms_p50: 300,
    llm_ttft_ms_p50: 400,
    tts_first_audio_ms_p50: 200,
    barge_in_cutoff_ms_p95: 250,
    fallback_count: 0,
    ...overrides,
  };
}

export function makeTruthDiffEntry(overrides: Partial<TruthVsCardDiffEntry> = {}): TruthVsCardDiffEntry {
  return {
    field_path: 'address.house',
    label_ru: 'Дом',
    world_fact_id: 'fact-1',
    world_value: '27',
    card_value: '72',
    verdict: 'MISMATCH',
    ...overrides,
  };
}

export function makeHandoffSnapshot(overrides: Partial<HandoffSnapshotView> = {}): HandoffSnapshotView {
  return {
    snapshot_id: 'snapshot-1',
    incident_id: 'incident-1',
    card_id: 'card-1',
    card_revision_id: 'revision-1',
    card_values: { 'address.house': '72' },
    recipient_services: ['FIRE_RESCUE'],
    created_by_user_id: 'user-1',
    created_at_offset_ms: 5000,
    content_sha256: 'sha-abc',
    ...overrides,
  };
}

export function makeOperatorCardView(overrides: Partial<OperatorCardView> = {}): OperatorCardView {
  return {
    card_id: 'card-1',
    incident_id: 'incident-1',
    values: { 'address.house': '72', 'flags.threat_to_life': true },
    revision_counter: 3,
    field_specs: [
      { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'Дом', scoring_relevant: true, required_for_handoff: true },
      { field_path: 'flags.threat_to_life', value_type: 'BOOLEAN', enum_name: null, label_ru: 'Угроза жизни', scoring_relevant: true, required_for_handoff: true },
    ],
    ...overrides,
  };
}

export function makeSessionDetail(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: 'session-1',
    scenario_version_id: 'scenario-version-1',
    scenario_slug: 'apartment-fire',
    scenario_version: 1,
    session_mode: 'SINGLE_ROLE',
    state: 'COMPLETED',
    session_seed: 'seed',
    time_scale: 1,
    incident_id: 'incident-1',
    role_chain: ['OPERATOR_112'],
    stages: [],
    active_role_stage_id: null,
    participants: [],
    created_by_user_id: 'instructor-1',
    created_at: '2026-09-21T00:00:00Z',
    started_at: '2026-09-21T00:00:01Z',
    completed_at: '2026-09-21T00:10:00Z',
    abort_reason: null,
    monotonic_offset_ms: 600000,
    last_seq_no: 40,
    transition_pause_seconds: 5,
    transition_continue_available_at_offset_ms: null,
    variants: {
      card_source: 'CALLER_VOICE',
      dds_mode: 'RESOURCE_PICKER',
      dds_card_check: 'OFF',
      dds_brigade_call: 'OFF',
    },
    scenario_role_chain: ['OPERATOR_112'],
    lesson_id: null,
    lesson_position: null,
    ...overrides,
  };
}

export function makeSessionReport(overrides: Partial<SessionReport> = {}): SessionReport {
  return {
    session_id: 'session-1',
    session: makeSessionDetail(),
    score_report: makeScoreReport(),
    timeline: [makeTimelineEntry()],
    transcript: [makeTranscriptSegment()],
    audio_segments: [makeAudioSegment()],
    final_card: makeOperatorCardView(),
    truth_vs_card_diff: [makeTruthDiffEntry()],
    handoff: makeHandoffSnapshot(),
    dds_decisions: [makeDdsDecision()],
    resource_timeline: [makeResourceTimelineEntry()],
    timing_metrics: makeTimingMetrics(),
    explanation_available: false,
    released: false,
    ...overrides,
  };
}

export function makeReportExplanation(overrides: Partial<ReportExplanation> = {}): ReportExplanation {
  return {
    session_id: 'session-1',
    audience: 'TRAINEE',
    text_ru: 'Вы хорошо собрали данные, но допустили ошибку в адресе.',
    generated_at: '2026-09-21T00:11:00Z',
    llm_provider: 'fake',
    llm_model: 'fake-llm',
    score_report_checksum: 'checksum-abc',
    ...overrides,
  };
}

export function makeInferenceMetric(overrides: Partial<InferenceMetricView> = {}): InferenceMetricView {
  return {
    id: 'metric-1',
    session_id: 'session-1',
    request_id: 'request-1',
    component: 'ASR',
    provider: 'giga-am',
    model: 'v3_e2e_ctc',
    model_version: null,
    turn_index: 0,
    input_tokens: null,
    input_duration_ms: 2000,
    output_tokens: null,
    output_audio_ms: null,
    started_at: '2026-09-21T00:00:01Z',
    first_output_at: '2026-09-21T00:00:01.3Z',
    finished_at: '2026-09-21T00:00:01.4Z',
    ttft_ms: 300,
    total_latency_ms: 400,
    tokens_per_second: null,
    realtime_factor: null,
    gpu_memory_mb: null,
    fallback_count: 0,
    retry_count: 0,
    ...overrides,
  };
}

export function makeInferenceMetricsPage(overrides: Partial<InferenceMetricsPage> = {}): InferenceMetricsPage {
  return {
    items: [makeInferenceMetric()],
    total: 1,
    timing_metrics: makeTimingMetrics(),
    ...overrides,
  };
}
