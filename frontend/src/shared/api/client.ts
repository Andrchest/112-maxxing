// Typed helpers over the generated OpenAPI schema (D12, D8). Every request/response shape here
// is derived from `operations[...]`/`components[...]` in `./schema.d.ts` — this file is the only
// place allowed to describe a REST call by its operationId; nothing hand-duplicates a generated
// DTO (see `src/app/no-duplicate-dto-guard.test.ts`).
import { apiFetch, getAuthToken, ProblemError, type ProblemDetails } from '@/shared/lib/api';
import { API_BASE_PATH } from '@/shared/config';
import { ru } from '@/shared/i18n/ru';
import type { components, operations } from './schema';

export type LoginRequest = operations['loginUser']['requestBody']['content']['application/json'];
export type TokenResponse = operations['loginUser']['responses']['200']['content']['application/json'];
export type UserAccount = components['schemas']['UserAccount'];
export type UserRole = components['schemas']['UserRole'];
export type RoleType = components['schemas']['RoleType'];
export type SessionMode = components['schemas']['SessionMode'];
export type HealthReadyResponse = components['schemas']['HealthReadyResponse'];
export type HealthStatus = components['schemas']['HealthStatus'];
export type ScenarioSummary = components['schemas']['ScenarioSummary'];
export type ScenarioVersionListItem = components['schemas']['ScenarioVersionListItem'];
export type ParticipantAssignment = components['schemas']['ParticipantAssignment'];
export type SessionCreateRequest = operations['createSession']['requestBody']['content']['application/json'];
export type SessionDetail = operations['createSession']['responses']['201']['content']['application/json'];
export type ProblemCode = components['schemas']['ProblemCode'];
// -- I3 E1: variant switches (70 §70.2) ------------------------------------------------------
export type CardSource = components['schemas']['CardSource'];
export type DdsMode = components['schemas']['DdsMode'];
export type DdsCardCheck = components['schemas']['DdsCardCheck'];
export type DdsBrigadeCall = components['schemas']['DdsBrigadeCall'];
export type SessionVariants = components['schemas']['SessionVariants'];
export type VariantsRequest = components['schemas']['VariantsRequest'];
export type ScenarioVariantsView = components['schemas']['ScenarioVariantsView'];

// -- E8-B: operator console (SPEC §9, §10, §32, §39; D3, D12) --------------------------------
// Additive to E8-A's client (client.ts is "the only place allowed to describe a REST call by its
// operationId", D12 design decision #1) — not in this task's original FILES list, but required by
// it: the console cannot call any `/operator/*` command without a typed wrapper here, and
// `no-duplicate-dto-guard.test.ts` already forbids re-declaring these shapes elsewhere.
export type SessionListItem = components['schemas']['SessionListItem'];
export type SessionState = components['schemas']['SessionState'];
export type SessionSnapshot = components['schemas']['SessionSnapshot'];
export type OperatorStageView = components['schemas']['OperatorStageView'];
export type CallStateView = components['schemas']['CallStateView'];
export type OperatorCardView = components['schemas']['OperatorCardView'];
export type CardFieldSpec = components['schemas']['CardFieldSpec'];
export type FactValue = components['schemas']['FactValue'];
// I3 E2a (70 §70.6.3, D18): a service is a catalog id, a plain string (the contract keeps its old
// schema name so every `$ref` survives); the frontend names it by what it is.
export type ServiceId = components['schemas']['ServiceCatalogEntry']['id'];
export type ServiceSelectionView = components['schemas']['ServiceSelectionView'];
export type ActionDescriptor = components['schemas']['ActionDescriptor'];
export type SetCardFieldRequest = operations['setCardField']['requestBody']['content']['application/json'];
export type SetCardFieldResponse = operations['setCardField']['responses']['200']['content']['application/json'];
export type EndCallRequest = operations['endCall']['requestBody']['content']['application/json'];

export function listSessions(
  params: { scope?: 'MINE' | 'ALL'; state?: SessionState } = {},
): Promise<{ items: SessionListItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params.scope) query.set('scope', params.scope);
  if (params.state) query.set('state', params.state);
  const qs = query.toString();
  return apiFetch(`/sessions${qs ? `?${qs}` : ''}`);
}

/** The browser-refresh restore payload (SPEC §39, §42 test 13; `docs/hld/40-realtime-protocol.md`
 * §40.5): active stage, `available_actions`, the role's card, call state and `last_seq_no`. */
export function getSessionSnapshot(sessionId: string): Promise<SessionSnapshot> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/snapshot`);
}

// -- I3 E0 (D10): the REST twin of the WebSocket replay ------------------------------------
// `listSessionEvents` is "the same envelopes, the same per-role filtering ... and the same
// payload redaction table" (openapi.yaml) as the WS stream — used to hydrate a panel that reads
// `entities/session`'s event log (e.g. the operator transcript) with what already happened before
// this page mounted, since a fresh WS connection only replays from `last_seq_no` forward.
export type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
export type SessionEventPage = components['schemas']['SessionEventPage'];

export function listSessionEvents(
  sessionId: string,
  params: { afterSeqNo?: number; limit?: number; eventType?: components['schemas']['EventType'][] } = {},
): Promise<SessionEventPage> {
  const query = new URLSearchParams();
  if (params.afterSeqNo !== undefined) query.set('after_seq_no', String(params.afterSeqNo));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  for (const eventType of params.eventType ?? []) query.append('event_type', eventType);
  const qs = query.toString();
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/events${qs ? `?${qs}` : ''}`);
}

export function answerCall(sessionId: string): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/call/answer`, { method: 'POST' });
}

export function endCall(sessionId: string, body: EndCallRequest): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/call/end`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// -- E11-C: the LiveKit call widget (SPEC §15, §32, §34; D9, D12) ---------------------------
export type VoiceTokenResponse = components['schemas']['VoiceTokenResponse'];

/** Mints a room-scoped LiveKit token for the calling participant (D9: "the backend is the only
 * minter of LiveKit tokens — the frontend never holds the LiveKit API secret"). Call this only
 * once per join, after the server reports the call CONNECTED; the widget itself is responsible
 * for not requesting a second token for the same call. */
export function createVoiceToken(sessionId: string): Promise<VoiceTokenResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/voice-token`, { method: 'POST' });
}

/** Exactly one `field_path` per command (SPEC §9: every mutation stored with actor/previous/new
 * value). */
export function setCardField(sessionId: string, body: SetCardFieldRequest): Promise<SetCardFieldResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/card/field`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function selectRecipientService(sessionId: string, serviceType: ServiceId): Promise<ServiceSelectionView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/services/select`, {
    method: 'POST',
    body: JSON.stringify({ service_type: serviceType }),
  });
}

export function deselectRecipientService(sessionId: string, serviceType: ServiceId): Promise<ServiceSelectionView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/services/deselect`, {
    method: 'POST',
    body: JSON.stringify({ service_type: serviceType }),
  });
}

export function beginHandoffPreparation(sessionId: string): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/handoff/prepare`, { method: 'POST' });
}

export function backToInterview(sessionId: string): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/handoff/cancel`, { method: 'POST' });
}

// -- E10: handoff/complete_stage/continue + the DDS console (SPEC §10, §11, §32, §39; D3, D12) ---
// Every DDS command returns a `DdsStageView` (D8 materialized view) — wholesale-replaced by the
// caller, same pattern as `OperatorStageView` above (D12 design decision #1).
export type CreateHandoffRequest = NonNullable<operations['createHandoff']['requestBody']>['content']['application/json'];
export type HandoffSnapshotView = components['schemas']['HandoffSnapshotView'];
export type HandoffCreatedView = components['schemas']['HandoffCreatedView'];
export type DdsWorkItem = components['schemas']['DdsWorkItem'];
export type DdsStageView = components['schemas']['DdsStageView'];
export type DDSStageState = components['schemas']['DDSStageState'];
export type ResourceType = components['schemas']['ResourceType'];
export type ResourceStatus = components['schemas']['ResourceStatus'];
export type ResourceCapability = components['schemas']['ResourceCapability'];
export type EtaProfileView = components['schemas']['EtaProfileView'];
export type EmergencyResourceView = components['schemas']['EmergencyResourceView'];
export type ResourceSelectionRequest = components['schemas']['ResourceSelectionRequest'];
export type DispatchRequest = components['schemas']['DispatchRequest'];
export type DispatchResultView = components['schemas']['DispatchResultView'];
export type StatusUpdateKind = components['schemas']['StatusUpdateKind'];
export type StatusUpdateRequest = components['schemas']['StatusUpdateRequest'];
export type StatusUpdateView = components['schemas']['StatusUpdateView'];
// -- I3 E5a/E5b: the memo's per-leg statuses and card-check flags (70 §70.4.2/§70.4.3/§70.7, D16) --
export type DdsLegView = components['schemas']['DdsLegView'];
export type ServiceResponseStatus = components['schemas']['ServiceResponseStatus'];
export type ServiceStatusEntryView = components['schemas']['ServiceStatusEntryView'];
export type SetServiceStatusRequest = components['schemas']['SetServiceStatusRequest'];
export type CardIssueKind = components['schemas']['CardIssueKind'];
export type FlagCardIssueRequest = components['schemas']['FlagCardIssueRequest'];
export type CardIssueView = components['schemas']['CardIssueView'];
export type NotificationSeverity = components['schemas']['NotificationSeverity'];
export type NotificationView = components['schemas']['NotificationView'];
export type RadioMessageView = components['schemas']['RadioMessageView'];
export type ClosureReason = components['schemas']['ClosureReason'];
export type CloseIncidentRequest = components['schemas']['CloseIncidentRequest'];

/** Freezes the card into a `HandoffSnapshot` and creates one `DDSAssignment` per recipient
 * service (SPEC §10). `comment_ru` is optional trainee-entered context, not a required field. */
export function createHandoff(sessionId: string, body: CreateHandoffRequest = {}): Promise<HandoffCreatedView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/handoff`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function completeOperatorStage(sessionId: string): Promise<SessionDetail> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/stage/complete`, { method: 'POST' });
}

/** Fires `finish_role_transition`; refused with `409 INVALID_TRANSITION` before the pause elapses
 * or before the next stage has an assigned participant (SPEC §10.10). */
export function continueToNextStage(sessionId: string): Promise<SessionDetail> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/stage/continue`, { method: 'POST' });
}

/** Assembled from `handoff_snapshots` + `dds_assignments` only — never `WorldTruth` (D3, SPEC §42
 * test 3). Rarely called directly; the snapshot/`DdsStageView` already embed it. */
export function getDdsWorkItem(sessionId: string): Promise<DdsWorkItem> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/work-item`);
}

export function acknowledgeDdsAssignment(sessionId: string): Promise<DdsStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/acknowledge`, { method: 'POST' });
}

/** Fires `open_resource_selection` (`ACKNOWLEDGED`/`DISPATCHED`/`EN_ROUTE`/`ARRIVED`/`WORKING` ->
 * `RESOURCE_SELECTION`, additive endpoint landed after this epic's initial cut — see the report's
 * "Follow-up"). */
export function openDdsResourceSelection(sessionId: string): Promise<DdsStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources/selection/open`, { method: 'POST' });
}

/** Fires `back_to_acknowledged` (`RESOURCE_SELECTION` -> `ACKNOWLEDGED`, guard
 * `guard_no_resource_selected`) — the mirror of {@link openDdsResourceSelection}. */
export function backToDdsAcknowledged(sessionId: string): Promise<DdsStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources/selection/cancel`, { method: 'POST' });
}

export function listDdsResources(
  sessionId: string,
  params: { serviceType?: ServiceId; status?: ResourceStatus[] } = {},
): Promise<{ items: EmergencyResourceView[]; total: number }> {
  const query = new URLSearchParams();
  if (params.serviceType) query.set('service_type', params.serviceType);
  for (const status of params.status ?? []) query.append('status', status);
  const qs = query.toString();
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources${qs ? `?${qs}` : ''}`);
}

export function selectDdsResource(sessionId: string, resourceId: string): Promise<DdsStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources/select`, {
    method: 'POST',
    body: JSON.stringify({ resource_id: resourceId } satisfies ResourceSelectionRequest),
  });
}

export function deselectDdsResource(sessionId: string, resourceId: string): Promise<DdsStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources/deselect`, {
    method: 'POST',
    body: JSON.stringify({ resource_id: resourceId } satisfies ResourceSelectionRequest),
  });
}

/** Fires `dispatch` the first time, `dispatch_additional` afterwards — same endpoint either way
 * (`DispatchResultView.is_additional` tells the two apart), per the manager's E10 addendum. */
export function dispatchDdsResources(sessionId: string, body: DispatchRequest = {}): Promise<DispatchResultView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/resources/dispatch`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function sendDdsStatusUpdate(sessionId: string, body: StatusUpdateRequest): Promise<StatusUpdateView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/status-updates`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `GET /dds/legs` (`listDdsLegs`, I3 E5a) — every notified service's block, broadcast to every
 * ДДС participant; only `is_mine`/`available_actions` are the caller's own (§70.4.3). */
export function listDdsLegs(sessionId: string): Promise<DdsLegView[]> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/legs`);
}

/** `POST /dds/legs/{id}/open` (`openDdsCard`, I3 E5a) — `ADDED --receive--> RECEIVED`; idempotent
 * past `ADDED` (§70.4.2). */
export function openDdsCard(sessionId: string, assignmentId: string): Promise<DdsLegView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/legs/${encodeURIComponent(assignmentId)}/open`, {
    method: 'POST',
  });
}

/** `POST /dds/legs/{id}/status` (`setDdsServiceStatus`, I3 E5a) — the memo's pencil form: fires
 * one `SERVICE_RESPONSE_TRANSITIONS` trigger (§70.4.2). */
export function setDdsServiceStatus(sessionId: string, assignmentId: string, body: SetServiceStatusRequest): Promise<DdsLegView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/legs/${encodeURIComponent(assignmentId)}/status`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `POST /dds/card-issues` (`flagDdsCardIssue`, I3 E5b) — «Отметить ошибку в карточке», offered
 * only under `dds_card_check: ON` (§70.4.4, §70.7, C1). */
export function flagDdsCardIssue(sessionId: string, body: FlagCardIssueRequest): Promise<CardIssueView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/card-issues`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `GET /dds/notifications` — same endpoint for the Operator 112 and DDS consoles (both hold
 * `ACKNOWLEDGE_NOTIFICATION`); the backend filters by the caller's role server-side. */
export function listNotifications(
  sessionId: string,
  params: { unacknowledgedOnly?: boolean } = {},
): Promise<{ items: NotificationView[]; total: number }> {
  const query = new URLSearchParams();
  if (params.unacknowledgedOnly) query.set('unacknowledged_only', 'true');
  const qs = query.toString();
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/notifications${qs ? `?${qs}` : ''}`);
}

export function acknowledgeNotification(sessionId: string, notificationId: string): Promise<NotificationView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/notifications/${encodeURIComponent(notificationId)}/acknowledge`, {
    method: 'POST',
  });
}

export function listRadioMessages(
  sessionId: string,
  params: { afterSeqNo?: number; limit?: number } = {},
): Promise<{ items: RadioMessageView[]; last_seq_no: number }> {
  const query = new URLSearchParams();
  if (params.afterSeqNo !== undefined) query.set('after_seq_no', String(params.afterSeqNo));
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/radio-messages${qs ? `?${qs}` : ''}`);
}

export function closeDdsIncident(sessionId: string, body: CloseIncidentRequest): Promise<SessionDetail> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds/close`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// -- E16: post-session report and replay (SPEC §29, §2; D11, D12; openapi `reports`/`instructor`) --
// `getSessionReport` reads stored scores only (R1) — never triggers a recompute. Every section the
// caller may not see comes back empty/null per the schema's own nullability (R3); this file just
// forwards the envelope, it never filters or re-aggregates anything client-side.
export type SessionReport = components['schemas']['SessionReport'];
export type ScoreReportView = components['schemas']['ScoreReportView'];
export type ScoreResultView = components['schemas']['ScoreResultView'];
export type ScoreEvidenceView = components['schemas']['ScoreEvidenceView'];
export type ScoreCategoryTotalView = components['schemas']['ScoreCategoryTotalView'];
export type ScoringCategory = components['schemas']['ScoringCategory'];
export type TranscriptSegmentView = components['schemas']['TranscriptSegmentView'];
export type AudioSegmentRef = components['schemas']['AudioSegmentRef'];
export type TimelineEntryView = components['schemas']['TimelineEntryView'];
export type EventType = components['schemas']['EventType'];
export type ActorType = components['schemas']['ActorType'];
export type DdsDecisionView = components['schemas']['DdsDecisionView'];
export type ResourceTimelineEntryView = components['schemas']['ResourceTimelineEntryView'];
export type TimingMetricsView = components['schemas']['TimingMetricsView'];
export type TruthVsCardDiffEntry = components['schemas']['TruthVsCardDiffEntry'];
export type TruthVsCardDiffVerdict = TruthVsCardDiffEntry['verdict'];
export type ReportReleaseView = components['schemas']['ReportReleaseView'];
export type GenerateExplanationRequest = NonNullable<operations['generateReportExplanation']['requestBody']>['content']['application/json'];
export type ExplanationAudience = GenerateExplanationRequest['audience'];
export type ReportExplanation = components['schemas']['ReportExplanation'];
export type InferenceMetricView = components['schemas']['InferenceMetricView'];
export type InferenceMetricComponent = InferenceMetricView['component'];
export type InferenceMetricsPage = components['schemas']['InferenceMetricsPage'];
// -- I4 E35: text quality, «Грамотность и адреса» (71 §71.12, D35) — report-only, no score effect.
export type TextQualityReportView = components['schemas']['TextQualityReportView'];
export type TextQualityFieldView = components['schemas']['TextQualityFieldView'];
export type MisspelledSpanView = components['schemas']['MisspelledSpanView'];
export type StreetLookupView = components['schemas']['StreetLookupView'];
export type TextQualitySource = TextQualityFieldView['source'];
export type StreetStatusKind = StreetLookupView['status'];

/** `getSessionReport` (R1: stored `score_results`/`score_evidence` echoed as-is, never
 * recomputed). `409` = the existing `ReportNotReadyError`/`REPORT_NOT_READY` (session not
 * COMPLETED or ABORTED-and-unscored); `403 REPORT_NOT_RELEASED` gates a trainee before release
 * (R3). */
export function getSessionReport(sessionId: string): Promise<SessionReport> {
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}`);
}

/** Fetches one `audio_segments` row's WAV bytes as a `Blob` (D9, D12 design decision #2). An
 * `<audio>` element cannot carry a Bearer header, so the report fetches the segment itself
 * (bypassing {@link apiFetch}'s JSON-only assumption) and hands the caller a `Blob` to turn into
 * an object URL — `shared/media/report-audio.ts` computes the seek offset,
 * `features/report/transcript-audio-panel.tsx` owns `URL.revokeObjectURL` on unmount/segment
 * change. Throws {@link ProblemError} for `404`/`410 AUDIO_PURGED`. */
export async function getAudioSegment(sessionId: string, audioSegmentId: string): Promise<Blob> {
  const headers: Record<string, string> = { Accept: 'audio/wav, application/problem+json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(
    `${API_BASE_PATH}/sessions/${encodeURIComponent(sessionId)}/audio/${encodeURIComponent(audioSegmentId)}`,
    { headers },
  );

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/problem+json')) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return await response.blob();
}

// -- I5 E40: MP3 download (Q-E16-3 variant b, ТЗ ¶383) — the same segment `getAudioSegment` plays,
// as a downloadable `audio/mpeg` file (same fetch-with-Bearer-token pattern, same problem mapping).
/** `getAudioSegmentMp3`: mono 64 kbit/s CBR MP3 of one `audio_segments` row, cached server-side by
 * content hash — a repeat call for the same segment is a cache hit, not a re-encode. Same access
 * rule and problems as {@link getAudioSegment} (`404`/`410 AUDIO_PURGED`). */
export async function getAudioSegmentMp3(sessionId: string, audioSegmentId: string): Promise<Blob> {
  const headers: Record<string, string> = { Accept: 'audio/mpeg, application/problem+json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(
    `${API_BASE_PATH}/sessions/${encodeURIComponent(sessionId)}/audio/${encodeURIComponent(audioSegmentId)}/mp3`,
    { headers },
  );

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/problem+json')) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return await response.blob();
}

/** `404` when none has been generated yet (openapi) — the caller checks
 * `SessionReport.explanation_available` first and skips this call otherwise. */
export function getReportExplanation(sessionId: string): Promise<ReportExplanation> {
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}/explanation`);
}

/** `409 REPORT_NOT_READY` before deterministic scores exist, `409 EXPLANATION_ALREADY_EXISTS`
 * without `regenerate: true`, `503 LLM_UNAVAILABLE` on a model timeout — the report itself is
 * unaffected either way (SPEC §2, §26, §41). */
export function generateReportExplanation(
  sessionId: string,
  body: GenerateExplanationRequest = { regenerate: false, audience: 'TRAINEE' },
): Promise<ReportExplanation> {
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}/explanation`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** SPEC §27 telemetry (`InferenceMetricsPage.timing_metrics` is the same aggregate
 * `SessionReport.timing_metrics` carries — one function serves both, per the recon). */
export function listInferenceMetrics(
  sessionId: string,
  params: { component?: InferenceMetricComponent; limit?: number } = {},
): Promise<InferenceMetricsPage> {
  const query = new URLSearchParams();
  if (params.component) query.set('component', params.component);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}/inference-metrics${qs ? `?${qs}` : ''}`);
}

/** `instructor` tag (R2: release belongs to E16). INSTRUCTOR/ADMIN only; idempotent — a second
 * call returns the first release unchanged. Emits no event (openapi `x-emits: []`). */
export function releaseReportToTrainee(sessionId: string): Promise<ReportReleaseView> {
  return apiFetch(`/instructor/sessions/${encodeURIComponent(sessionId)}/report/release`, { method: 'POST' });
}

// -- E17-C: instructor live overview (SPEC §7, §13; D6, HLD §10.8/§10.10/§10.13, R4) ----------
// `InstructorSessionOverview` is "the union of the two trainee views plus the hidden layers" per
// its own openapi description — `WorldTruthView`/`CallerBeliefView` are exposed ONLY here and in
// the report's truth diff (D3, R4); no other file may import these two types
// (`app/no-world-truth-guard.test.ts`).
export type RoleStageView = components['schemas']['RoleStageView'];
export type WorldTruthView = components['schemas']['WorldTruthView'];
export type CallerBeliefView = components['schemas']['CallerBeliefView'];
export type KnowledgeState = components['schemas']['KnowledgeState'];
export type EmotionLabel = components['schemas']['EmotionLabel'];
export type GateOutcome = components['schemas']['GateOutcome'];
export type GateReason = components['schemas']['GateReason'];
export type GateDecisionView = components['schemas']['GateDecisionView'];
export type GateTurnView = components['schemas']['GateTurnView'];
export type StageState = components['schemas']['StageState'];
export type InstructorSessionOverview = components['schemas']['InstructorSessionOverview'];

/** `getInstructorSessionOverview` (R4): a READ, emits and writes nothing. INSTRUCTOR/ADMIN only
 * (`403 FORBIDDEN_FOR_ROLE` for anyone else); works in every session state after creation, incl.
 * `COMPLETED`/`ABORTED` (openapi.yaml, R4). */
export function getInstructorSessionOverview(sessionId: string): Promise<InstructorSessionOverview> {
  return apiFetch(`/instructor/sessions/${encodeURIComponent(sessionId)}/overview`);
}

export function login(body: LoginRequest): Promise<TokenResponse> {
  return apiFetch<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function getCurrentUser(): Promise<UserAccount> {
  return apiFetch<UserAccount>('/auth/me');
}

/** `GET /users` (additive, E7; CHANGED I4 E28) — INSTRUCTOR/ADMIN only. `role` narrows to one
 * `UserRole` (used by E8-B's trainee picker to list only `TRAINEE` accounts). `includeInactive`
 * is ADMIN only (`403` for an INSTRUCTOR that passes it, openapi.yaml) — added for the admin
 * «Пользователи» tab (I4 E30, 71 §71.7); every existing caller keeps working unchanged since the
 * param is optional and defaults to omitted (server default `false`). Items are `UserAccountI4`
 * (adds `is_active`) since E28 landed — the wider type is additive over the plain `UserAccount`
 * every pre-I4 caller already reads. */
export async function listUsers(
  params: { role?: UserRole; includeInactive?: boolean } = {},
): Promise<{ items: UserAccountI4[]; total: number }> {
  // I6 FIX1: the endpoint pages (server default `limit` 50, `username` order), and a single call
  // silently dropped every account past the first page — e.g. a newly created blocked user behind
  // older `e2e-…` logins. Walk the pages (by `offset`) until `total` is reached so every caller
  // sees the whole roster; the first request is unchanged.
  const items: UserAccountI4[] = [];
  let total: number;
  for (;;) {
    const query = new URLSearchParams();
    if (params.role) query.set('role', params.role);
    if (params.includeInactive) query.set('include_inactive', 'true');
    if (items.length > 0) query.set('offset', String(items.length));
    const qs = query.toString();
    const page = await apiFetch<{ items: UserAccountI4[]; total: number }>(`/users${qs ? `?${qs}` : ''}`);
    items.push(...page.items);
    total = page.total;
    if (page.items.length === 0 || items.length >= total) break;
  }
  return { items, total };
}

/**
 * `GET /health/ready` answers `200` when every required component is `READY` and `503`
 * otherwise (D8, SPEC §37) — both carry the same, perfectly normal `HealthReadyResponse` body.
 * This bypasses {@link apiFetch}'s "non-2xx is an error" rule instead of throwing on a readiness
 * report that only says "not ready yet".
 */
export async function getHealthReady(): Promise<HealthReadyResponse> {
  const response = await fetch(`${API_BASE_PATH}/health/ready`, {
    headers: { Accept: 'application/json' },
  });
  return (await response.json()) as HealthReadyResponse;
}

/** Every picker's default read: `include_archived` is not passed, so an archived scenario is
 * never offered here (I4 E32, ТЗ ¶229). {@link listScenarioPage} takes `includeArchived` for the
 * instructor's own scenario management view. */
export function listScenarios(): Promise<{ items: ScenarioSummary[]; total: number }> {
  return apiFetch('/scenarios');
}

export function listScenarioVersions(
  scenarioId: string,
): Promise<{ items: ScenarioVersionListItem[]; total: number }> {
  return apiFetch(`/scenarios/${scenarioId}/versions`);
}

// -- I3 E4b (manager follow-up): the lesson plan/card rows show the scenario's Russian title,
// not a bare position (D3: this is the trainee-safe projection, free of WorldTruth etc.).
export type ScenarioVersionTraineeSummary = components['schemas']['ScenarioVersionTraineeSummary'];

export function getScenarioVersionSummary(scenarioVersionId: string): Promise<ScenarioVersionTraineeSummary> {
  return apiFetch(`/scenarios/versions/${encodeURIComponent(scenarioVersionId)}/summary`);
}

export function createSession(body: SessionCreateRequest): Promise<SessionDetail> {
  return apiFetch<SessionDetail>('/sessions', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function startSession(sessionId: string): Promise<SessionDetail> {
  return apiFetch<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}/start`, {
    method: 'POST',
  });
}

// -- E20-E R11: abortSession client wrapper (INSTRUCTOR/ADMIN, confirm dialog on the live overview) --
export type AbortSessionRequest = operations['abortSession']['requestBody']['content']['application/json'];

/** Fires `abort` (`CREATED|READY|ACTIVE|ROLE_TRANSITION -> ABORTED`, openapi.yaml). The event log
 * is preserved, never deleted (SPEC §39, §42 test 14) — this only ends the exercise early. */
export function abortSession(sessionId: string, body: AbortSessionRequest): Promise<SessionDetail> {
  return apiFetch<SessionDetail>(`/sessions/${encodeURIComponent(sessionId)}/abort`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// -- I3 E2a: the reference pack (70 §70.6.1-§70.6.3, D18) --------------------------------------
// The service catalog («СЛУЖБЫ 112») is the source of every service's Russian name
// (`entities/service-catalog`); `include_hidden` also returns deprecated ids, so a label for an
// old log always resolves.
export type ServiceCatalogEntry = components['schemas']['ServiceCatalogEntry'];
export type ReferenceManifest = components['schemas']['ReferenceManifest'];

export function listReferenceServices(
  params: { pack?: string; includeHidden?: boolean; q?: string } = {},
): Promise<ServiceCatalogEntry[]> {
  const query = new URLSearchParams();
  if (params.pack) query.set('pack', params.pack);
  if (params.includeHidden) query.set('include_hidden', 'true');
  if (params.q) query.set('q', params.q);
  const qs = query.toString();
  return apiFetch(`/reference/services${qs ? `?${qs}` : ''}`);
}

// -- I3 E4b: lessons and the cross-session incident list (70 §70.3.6, D15) --------------------
// A Lesson owns N ordinary sessions; it has no event log of its own (D15) — every function here
// is a thin wrapper over `lessons`/`incidents`, same "typed helper over the generated schema"
// discipline as the rest of this file (D12 design decision #1).
export type LessonState = components['schemas']['LessonState'];
export type ArrivalKind = components['schemas']['ArrivalKind'];
export type CardStatus = components['schemas']['CardStatus'];
export type Arrival = components['schemas']['Arrival'];
export type LessonPlanEntry = components['schemas']['PlanEntry'];
export type LessonCreateRequest = operations['createLesson']['requestBody']['content']['application/json'];
export type LessonSessionView = components['schemas']['LessonSessionView'];
export type LessonListItem = components['schemas']['LessonListItem'];
export type LessonDetail = components['schemas']['LessonDetail'];
export type LessonReport = components['schemas']['LessonReport'];
export type IncidentListItem = components['schemas']['IncidentListItem'];

export function createLesson(body: LessonCreateRequest): Promise<LessonDetail> {
  return apiFetch('/lessons', { method: 'POST', body: JSON.stringify(body) });
}

export function listLessons(
  params: { scope?: 'MINE' | 'ALL'; state?: LessonState; limit?: number; offset?: number } = {},
): Promise<{ items: LessonListItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params.scope) query.set('scope', params.scope);
  if (params.state) query.set('state', params.state);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiFetch(`/lessons${qs ? `?${qs}` : ''}`);
}

export function getLesson(lessonId: string): Promise<LessonDetail> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}`);
}

/** `CREATED -> ACTIVE`; the `LessonRunner` then starts each card's session by arrival (70 §70.3.3). */
export function startLesson(lessonId: string): Promise<LessonDetail> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/start`, { method: 'POST' });
}

/** Aborts the lesson and every non-terminal card session (same `AbortSessionRequest` shape
 * {@link abortSession} uses). */
export function abortLesson(lessonId: string, body: AbortSessionRequest): Promise<LessonDetail> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/abort`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `409 REPORT_NOT_READY` until the lesson is `COMPLETED` or `ABORTED` (openapi.yaml). */
export function getLessonReport(lessonId: string): Promise<LessonReport> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/report`);
}

/** Releases every card report of the lesson to its trainees (idempotent, no event, `instructor` tag). */
export function releaseLessonReport(lessonId: string): Promise<LessonDetail> {
  return apiFetch(`/instructor/lessons/${encodeURIComponent(lessonId)}/report/release`, { method: 'POST' });
}

/** The caller's cross-session incident list (ДДС «Список происшествий», 112 «реестр», 70 §70.3.6).
 * `card_status` and the deadline offsets are read verbatim from the server — this file (and every
 * caller of it) never derives a status from timers or offsets. */
export function listMyIncidents(
  params: { lessonId?: string; roleType?: RoleType; cardStatus?: CardStatus; q?: string } = {},
): Promise<{ items: IncidentListItem[]; total: number }> {
  const query = new URLSearchParams();
  if (params.lessonId) query.set('lesson_id', params.lessonId);
  if (params.roleType) query.set('role_type', params.roleType);
  if (params.cardStatus) query.set('card_status', params.cardStatus);
  if (params.q) query.set('q', params.q);
  const qs = query.toString();
  return apiFetch(`/incidents${qs ? `?${qs}` : ''}`);
}

// -- I3 E9a: trainee groups, per-workstation cards and difficulty weights (70 §70.3.7) ---------
// Groups are named lists of trainees a lesson may be created for; weight proposals are stored
// by the server and never applied until `acceptWeightProposals` (scoring stays deterministic,
// SPEC §2, D11). Thin wrappers only — nothing here computes a weight.
export type TraineeGroup = components['schemas']['TraineeGroup'];
export type TraineeGroupRequest = components['schemas']['TraineeGroupRequest'];
export type ProposalSource = components['schemas']['ProposalSource'];
export type WeightProposalSet = components['schemas']['WeightProposalSet'];
export type WeightProposalLine = components['schemas']['WeightProposalLine'];

/** `listScenarios` with an explicit page size — the lesson plan's picker lists every ticket
 * scenario (the catalog is larger than the default page of 50). */
export function listScenarioPage(
  params: { limit?: number; offset?: number; includeArchived?: boolean } = {},
): Promise<{ items: ScenarioSummary[]; total: number }> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.includeArchived) query.set('include_archived', 'true');
  const qs = query.toString();
  return apiFetch(`/scenarios${qs ? `?${qs}` : ''}`);
}

export function listTraineeGroups(): Promise<{ items: TraineeGroup[]; total: number }> {
  return apiFetch('/trainee-groups?limit=200');
}

export function createTraineeGroup(body: TraineeGroupRequest): Promise<TraineeGroup> {
  return apiFetch('/trainee-groups', { method: 'POST', body: JSON.stringify(body) });
}

export function updateTraineeGroup(groupId: string, body: TraineeGroupRequest): Promise<TraineeGroup> {
  return apiFetch(`/trainee-groups/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function deleteTraineeGroup(groupId: string): Promise<void> {
  return apiFetch(`/trainee-groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' });
}

/** Asks the server for proposals (LLM, or the heuristic on any LLM failure); changes no weight. */
export function requestWeightProposals(lessonId: string): Promise<WeightProposalSet> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/weight-proposals`, { method: 'POST' });
}

/** `404 NOT_FOUND` until proposals have been requested. */
export function getWeightProposals(lessonId: string): Promise<WeightProposalSet> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/weight-proposals`);
}

/** The chosen positions' proposals become the plan's weights — the only such path. */
export function acceptWeightProposals(lessonId: string, positions: number[]): Promise<WeightProposalSet> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/weight-proposals/accept`, {
    method: 'POST',
    body: JSON.stringify({ positions }),
  });
}

// -- I3 E6b: the ДДС phone line (HLD 80 §80.3; openapi `dds-calls`) -----------------------------
export type DdsCallView = components['schemas']['DdsCallView'];
export type DdsCallKind = components['schemas']['DdsCallKind'];
export type DdsCallState = components['schemas']['DdsCallState'];
export type DdsCallEndReason = components['schemas']['DdsCallEndReason'];
export type StartDdsCallRequest = components['schemas']['StartDdsCallRequest'];
export type StartDdsCallResponse = components['schemas']['StartDdsCallResponse'];

/** `POST /dds-calls` (`startDdsCall`) — the ДДС trainee places a call; only under
 * `dds_brigade_call: ON` (`409 ACTION_NOT_AVAILABLE` otherwise, `409 DDS_LINE_BUSY` while the
 * trainee's line is taken). The answer carries the browser endpoint's room-scoped token. */
export function startDdsCall(sessionId: string, body: StartDdsCallRequest): Promise<StartDdsCallResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds-calls`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `GET /dds-calls` (`listDdsCalls`) — every ДДС call of the session, newest first; what restores
 * the phone widget after a refresh (INV 13). */
export function listDdsCalls(sessionId: string): Promise<DdsCallView[]> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds-calls`);
}

/** `GET /dds-calls/{call_id}` (`getDdsCall`). */
export function getDdsCall(sessionId: string, callId: string): Promise<DdsCallView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds-calls/${encodeURIComponent(callId)}`);
}

/** `POST /dds-calls/{call_id}/hang-up` (`hangUpDdsCall`) — «Положить трубку». */
export function hangUpDdsCall(sessionId: string, callId: string): Promise<DdsCallView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds-calls/${encodeURIComponent(callId)}/hang-up`, {
    method: 'POST',
  });
}

/** `createVoiceToken {call_id}` (additive, I3 E6b) — the token of a live ДДС call's room, for the
 * line's own trainee (re-join after a refresh, INV 13). The 112 call keeps `createVoiceToken`. */
export function createDdsCallVoiceToken(sessionId: string, callId: string): Promise<VoiceTokenResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/voice-token`, {
    method: 'POST',
    body: JSON.stringify({ call_id: callId }),
  });
}

// -- I3 E6c: the service head's call and the heard status (HLD 80 §80.3.3, §80.4) ---------------
export type PersonaView = components['schemas']['PersonaView'];

/** `POST /dds-calls/{call_id}/answer` (`answerDdsCall`) — «Ответить» on a brigade's ringing
 * INBOUND call (a `report: CALL_IN` step). The answer carries the room-scoped token. */
export function answerDdsCall(sessionId: string, callId: string): Promise<StartDdsCallResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/dds-calls/${encodeURIComponent(callId)}/answer`, {
    method: 'POST',
  });
}

/** `GET /reference/personas` (`listReferencePersonas`) — the ДДС phone's personas of a pack. */
export function listReferencePersonas(pack?: string): Promise<PersonaView[]> {
  const qs = pack ? `?pack=${encodeURIComponent(pack)}` : '';
  return apiFetch(`/reference/personas${qs}`);
}

// -- I4 E34: methodical materials, «Справочная база» (HLD 71 §71.11) ---------------------------
// The instructor's «Материалы» page (upload, list, archive) and the trainee's «Справочная база»
// (list, open or download) share these four calls.
export type TrainingMaterialView = components['schemas']['TrainingMaterialView'];

export function listMaterials(params: { includeArchived?: boolean } = {}): Promise<{ items: TrainingMaterialView[] }> {
  const qs = params.includeArchived ? '?include_archived=true' : '';
  return apiFetch(`/materials${qs}`);
}

/** `multipart/form-data` (`422 MATERIAL_TYPE_NOT_ALLOWED` off the allow-list, `422
 * MATERIAL_TOO_LARGE` over `SIM_MATERIAL_MAX_MB`) — bypasses {@link apiFetch}'s
 * `Content-Type: application/json` so the browser sets the multipart boundary itself, the same
 * reason {@link getAudioSegment} bypasses its JSON-only response assumption. */
export async function uploadMaterial(titleRu: string, file: File): Promise<TrainingMaterialView> {
  const body = new FormData();
  body.set('title_ru', titleRu);
  body.set('file', file);

  const headers: Record<string, string> = { Accept: 'application/json, application/problem+json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE_PATH}/materials`, { method: 'POST', headers, body });
  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/problem+json')) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as TrainingMaterialView;
}

export function archiveMaterial(materialId: string): Promise<TrainingMaterialView> {
  return apiFetch(`/materials/${encodeURIComponent(materialId)}/archive`, { method: 'POST' });
}

/** Fetches the file with the bearer token attached and returns it as a `Blob` the caller can hand
 * to `URL.createObjectURL` — the same `getAudioSegment` pattern (a plain `<a href>`/`<iframe src>`
 * cannot carry the `Authorization` header). `content-type` on the response says inline vs. attachment. */
export async function getMaterialFile(materialId: string): Promise<Blob> {
  const headers: Record<string, string> = { Accept: '*/*, application/problem+json' };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE_PATH}/materials/${encodeURIComponent(materialId)}/file`, { headers });
  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/problem+json')) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return await response.blob();
}

/**
 * Exhaustive `ProblemCode -> ru.ts key` table (D12 design decision #5). `Record<ProblemCode, …>`
 * means adding a member to the generated `ProblemCode` union without adding a row here fails
 * `tsc` — the exhaustiveness the brief asks for. Keep the Russian text itself in `ru.ts`; this
 * table only points at it.
 */
const PROBLEM_MESSAGE_KEYS: Record<ProblemCode, keyof typeof ru> = {
  UNAUTHENTICATED: 'problemUnauthenticated',
  FORBIDDEN_FOR_ROLE: 'problemForbiddenForRole',
  NOT_FOUND: 'problemNotFound',
  VALIDATION_ERROR: 'problemValidationError',
  INVALID_TRANSITION: 'problemInvalidTransition',
  ACTION_NOT_AVAILABLE: 'problemActionNotAvailable',
  PARTICIPANT_NOT_ASSIGNED: 'problemParticipantNotAssigned',
  INFERENCE_NOT_READY: 'problemInferenceNotReady',
  SCENARIO_INVALID: 'problemScenarioInvalid',
  SCENARIO_VERSION_LOCKED: 'problemScenarioVersionLocked',
  SCENARIO_VERSION_EXISTS: 'problemScenarioVersionExists',
  PREFAB_HANDOFF_REQUIRED: 'problemPrefabHandoffRequired',
  RECIPIENT_SERVICES_EMPTY: 'problemRecipientServicesEmpty',
  HANDOFF_ALREADY_CREATED: 'problemHandoffAlreadyCreated',
  CARD_FIELD_UNKNOWN: 'problemCardFieldUnknown',
  CARD_VALUE_TYPE_MISMATCH: 'problemCardValueTypeMismatch',
  RESOURCE_UNAVAILABLE: 'problemResourceUnavailable',
  SESSION_NOT_ACTIVE: 'problemSessionNotActive',
  REPORT_NOT_READY: 'problemReportNotReady',
  REPORT_NOT_RELEASED: 'problemReportNotReleased',
  EXPLANATION_ALREADY_EXISTS: 'problemExplanationAlreadyExists',
  LLM_UNAVAILABLE: 'problemLlmUnavailable',
  AUDIO_PURGED: 'problemAudioPurged',
  RANGE_NOT_SATISFIABLE: 'problemRangeNotSatisfiable',
  VARIANT_NOT_SUPPORTED: 'problemVariantNotSupported',
  VARIANT_NOT_AVAILABLE: 'problemVariantNotAvailable',
  REFERENCE_PACK_UNKNOWN: 'problemReferencePackUnknown',
  SERVICE_UNKNOWN: 'problemServiceUnknown',
  LESSON_NOT_ACTIVE: 'problemLessonNotActive',
  // additive, I3 E3a (concurrent worker): kept the exhaustive table compiling against the
  // regenerated `schema.d.ts` — not a card-schema feature of this task.
  CARD_OPTION_UNKNOWN: 'problemCardOptionUnknown',
  SERVICE_REMOVAL_FORBIDDEN: 'problemServiceRemovalForbidden', // additive, I3 E2b′
  COMMENT_REQUIRED: 'problemCommentRequired', // additive, I3 E5a
  FORBIDDEN_FOR_SERVICE: 'problemForbiddenForService', // additive, I3 E5a
  DDS_LINE_BUSY: 'problemDdsLineBusy', // additive, I3 E6b
  PROPOSAL_UNKNOWN: 'problemProposalUnknown', // additive, I3 E6c
  DIAL_NUMBER_UNKNOWN: 'problemDialNumberUnknown', // additive, I3 E6e (SIP gateway only)
  NO_ACTIVE_DDS_SESSION: 'problemNoActiveDdsSession', // additive, I3 E6e (SIP gateway only)
  USERNAME_TAKEN: 'problemUsernameTaken', // additive, I4 E28
  SELF_MODIFICATION_FORBIDDEN: 'problemSelfModificationForbidden', // additive, I4 E28
  LAST_ADMIN_REQUIRED: 'problemLastAdminRequired', // additive, I4 E28
  MATERIAL_TYPE_NOT_ALLOWED: 'problemMaterialTypeNotAllowed', // additive, I4 E34
  MATERIAL_TOO_LARGE: 'problemMaterialTooLarge', // additive, I4 E34
  BACKUP_REQUIRED: 'problemBackupRequired', // additive, I4 E29
  NOT_RESOURCE_OWNER: 'problemNotResourceOwner', // additive, I5 E39
  LOGIN_THROTTLED: 'problemLoginThrottled', // additive, I7 E51 (G5)
};

/** Russian message for a backend `ProblemCode` (D12 design decision #5). Every UI surface that
 * catches a {@link ProblemError} renders `problem.detail`/`problem.title` for logging only and
 * this message for the trainee/instructor. */
export function problemMessageRu(code: ProblemCode): string {
  return ru[PROBLEM_MESSAGE_KEYS[code]];
}

/** I7 E51 (G5, ТЗ ¶295): the login page's own `LOGIN_THROTTLED` message, with the wait time
 * `app.api.errors._extra_of` puts on `retry_after_s` (the same value as the `Retry-After`
 * header, repeated in the body for a client — like this one — that only reads JSON). Falls back
 * to `problemLoginThrottled`'s generic wording if the field is somehow missing. */
export function loginThrottledMessageRu(problem: ProblemDetails): string {
  const retryAfterS = problem.retry_after_s;
  if (typeof retryAfterS !== 'number' || !Number.isFinite(retryAfterS) || retryAfterS <= 0) {
    return ru.problemLoginThrottled;
  }
  return `Слишком много попыток входа. Повторите через ${Math.ceil(retryAfterS)} с.`;
}

// --- I4 E31: per-card timers and unfinished lesson cards (71 §71.8, D34) ---------------------------
export type CardTimersRequest = components['schemas']['CardTimersRequest'];
export type UnscoredCardView = components['schemas']['UnscoredCardView'];

// --- I4 E32: instructor misc — comments, scenario upload/archive (71 §71.9) -------------------
export type ResultCommentView = components['schemas']['ResultCommentView'];
export type ResultCommentRequest = components['schemas']['ResultCommentRequest'];
export type ScenarioImportRequest = components['schemas']['ScenarioImportRequest'];
export type ScenarioValidationReport = components['schemas']['ScenarioValidationReport'];

/** `listSessionComments` — instructor feedback on a session result, oldest first. The trainee
 * sees them exactly when {@link getSessionReport} is visible to them (`403 REPORT_NOT_RELEASED`
 * otherwise). */
export function listSessionComments(sessionId: string): Promise<{ items: ResultCommentView[] }> {
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}/comments`);
}

/** `createSessionComment` (INSTRUCTOR / ADMIN). An edit is a new row: pass the id it supersedes
 * as `replaces_comment_id` (append-only — nothing is ever updated in place). */
export function createSessionComment(
  sessionId: string,
  body: ResultCommentRequest,
): Promise<ResultCommentView> {
  return apiFetch(`/reports/${encodeURIComponent(sessionId)}/comments`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `listLessonComments` — the lesson equivalent; trainee access follows the lesson report's
 * release (every card released), not a per-session one. */
export function listLessonComments(lessonId: string): Promise<{ items: ResultCommentView[] }> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/comments`);
}

/** `createLessonComment` (INSTRUCTOR / ADMIN). */
export function createLessonComment(
  lessonId: string,
  body: ResultCommentRequest,
): Promise<ResultCommentView> {
  return apiFetch(`/lessons/${encodeURIComponent(lessonId)}/comments`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** `archiveScenario` (INSTRUCTOR / ADMIN) — «удалить неактуальный» (ТЗ ¶229). Idempotent; existing
 * sessions and versions are untouched (FK `RESTRICT` stays). */
export function archiveScenario(scenarioId: string): Promise<ScenarioSummary> {
  return apiFetch(`/scenarios/${encodeURIComponent(scenarioId)}/archive`, { method: 'POST' });
}

/** `unarchiveScenario` (INSTRUCTOR / ADMIN) — returns the scenario to the pickers. */
export function unarchiveScenario(scenarioId: string): Promise<ScenarioSummary> {
  return apiFetch(`/scenarios/${encodeURIComponent(scenarioId)}/unarchive`, { method: 'POST' });
}

/** `validateScenarioFile` (INSTRUCTOR / ADMIN) — a dry run that writes nothing and always answers
 * `200`; an invalid document is reported as `valid: false` plus issues, not as an error status. */
export function validateScenarioFile(body: ScenarioImportRequest): Promise<ScenarioValidationReport> {
  return apiFetch('/scenarios/validate', { method: 'POST', body: JSON.stringify(body) });
}

/** `importScenarioVersion` (INSTRUCTOR / ADMIN) — validates then stores; re-importing identical
 * content under the same version is a no-op `201` (idempotent). */
export function importScenarioVersion(body: ScenarioImportRequest): Promise<ScenarioVersionListItem> {
  return apiFetch('/scenarios/import', { method: 'POST', body: JSON.stringify(body) });
}

// --- I4 E33: reports, statistics, CSV, trainee history (71 §71.10) ------------------------------
export type NormView = components['schemas']['NormView'];
export type TraineeStatistics = components['schemas']['TraineeStatistics'];
export type TraineeStatisticsRow = components['schemas']['TraineeStatisticsRow'];
export type MyHistory = components['schemas']['MyHistory'];
export type MyHistorySession = components['schemas']['MyHistorySession'];
// --- I5 E36: norms (DDS_FILL), reaction time, trainee rating, workstation --------------------
export type LegReactionTimeView = components['schemas']['LegReactionTimeView'];
export type TraineeRating = components['schemas']['TraineeRating'];
export type TraineeRatingRow = components['schemas']['TraineeRatingRow'];

/** `getTraineeStatistics` / `getTraineeStatisticsCsv`'s filter: one trainee, one group's
 * members, and a `completed_at` window (`from` inclusive, `to` exclusive, ISO date-times). */
export type TraineeStatisticsQuery = NonNullable<operations['getTraineeStatistics']['parameters']['query']>;

function statisticsQueryString(params: TraineeStatisticsQuery, format?: ReportFileFormat): string {
  const query = new URLSearchParams();
  if (params.trainee_id) query.set('trainee_id', params.trainee_id);
  if (params.group_id) query.set('group_id', params.group_id);
  if (params.from) query.set('from', params.from);
  if (params.to) query.set('to', params.to);
  if (format) query.set('format', format);
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

/** `getTraineeStatistics` — one row per trainee, read from stored scores (D11). A TRAINEE gets
 * their own row only; asking for another `trainee_id` is `403 FORBIDDEN_FOR_ROLE`. */
export function getTraineeStatistics(params: TraineeStatisticsQuery = {}): Promise<TraineeStatistics> {
  return apiFetch(`/statistics${statisticsQueryString(params)}`);
}

/** `getMyHistory` — the caller's own row plus their completed sessions, newest first; a session
 * whose report is not visible yet has `score_percent: null`. */
export function getMyHistory(): Promise<MyHistory> {
  return apiFetch('/me/history');
}

/** (I7 E46b) The three downloadable formats every export endpoint answers — `csv` is the
 * existing one (I4 E33 / I5 E36), `xlsx`/`pdf` are this epic's addition; the session report has
 * no `csv` (see {@link getSessionReportExport}). */
export type ReportFileFormat = 'csv' | 'xlsx' | 'pdf';

const XLSX_MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

function mediaTypeOf(format: ReportFileFormat): string {
  return format === 'csv' ? 'text/csv' : format === 'xlsx' ? XLSX_MEDIA_TYPE : 'application/pdf';
}

/** `getLessonReportCsv` (`?format=`, I7 E46b) — the lesson report as a file, same access and
 * numbers as {@link getLessonReport}; `format` defaults to `csv`, and the request URL for that
 * default is unchanged since I4 E33 (no `?format=` at all — `format=csv` is the server's own
 * default too). Fetched through {@link fetchFile} below, like the E37 downloads. */
export function getLessonReportCsv(lessonId: string, format: ReportFileFormat = 'csv'): Promise<Blob> {
  const query = format === 'csv' ? '' : `?format=${format}`;
  return fetchFile(`/lessons/${encodeURIComponent(lessonId)}/report.csv${query}`, mediaTypeOf(format));
}

/** `getTraineeStatisticsCsv` (`?format=`, I7 E46b) — {@link getTraineeStatistics} as a file. */
export function getTraineeStatisticsCsv(
  params: TraineeStatisticsQuery = {},
  format: ReportFileFormat = 'csv',
): Promise<Blob> {
  const path = `/statistics.csv${statisticsQueryString(params, format === 'csv' ? undefined : format)}`;
  return fetchFile(path, mediaTypeOf(format));
}

/** `getTraineeRating` (I5 E36, Q-E12-2) — trainees ranked by average score percent, best first
 * (INSTRUCTOR / ADMIN only; same filters as {@link getTraineeStatistics}). */
export function getTraineeRating(params: TraineeStatisticsQuery = {}): Promise<TraineeRating> {
  return apiFetch(`/statistics/rating${statisticsQueryString(params)}`);
}

/** `getTraineeRatingCsv` (`?format=`, I7 E46b) — {@link getTraineeRating} as a file. */
export function getTraineeRatingCsv(
  params: TraineeStatisticsQuery = {},
  format: ReportFileFormat = 'csv',
): Promise<Blob> {
  const path = `/statistics/rating.csv${statisticsQueryString(params, format === 'csv' ? undefined : format)}`;
  return fetchFile(path, mediaTypeOf(format));
}

/** `getSessionReportExport` (I7 E46b, owner item 6) — the session report as Excel or PDF, same
 * access as {@link getSessionReport}. No CSV: the session report never had one to extend. */
export function getSessionReportExport(
  sessionId: string,
  format: Extract<ReportFileFormat, 'xlsx' | 'pdf'>,
): Promise<Blob> {
  return fetchFile(`/reports/${encodeURIComponent(sessionId)}/export?format=${format}`, mediaTypeOf(format));
}

// --- I4 E30: Admin UI (71 §71.7) — typed wrappers over E28's accounts and E29's monitoring
// operations; the contract itself is unchanged by this epic ("API. None new; it consumes the S4
// and S5 operations."), so this section only adds the client-side calls the admin screens need. ---
export type UserAccountI4 = components['schemas']['UserAccountI4'];
export type UserCreateRequest = operations['createUser']['requestBody']['content']['application/json'];
export type UserUpdateRequest = operations['updateUser']['requestBody']['content']['application/json'];
export type PasswordResetRequest = operations['resetUserPassword']['requestBody']['content']['application/json'];
export type AuditAction = components['schemas']['AuditAction'];
export type AuditOutcome = components['schemas']['AuditOutcome'];
export type AuditEntryView = components['schemas']['AuditEntryView'];
export type UsageStats = components['schemas']['UsageStats'];
export type ServerLoad = components['schemas']['ServerLoad'];
export type ErrorRecordView = components['schemas']['ErrorRecordView'];
export type AdminAlertView = components['schemas']['AdminAlertView'];
export type BackupStatus = components['schemas']['BackupStatus'];

/** `createUser` (ADMIN) — ТЗ ¶195. `409 USERNAME_TAKEN`, `422 VALIDATION_ERROR` on a short
 * password. */
export function createUser(body: UserCreateRequest): Promise<UserAccountI4> {
  return apiFetch('/admin/users', { method: 'POST', body: JSON.stringify(body) });
}

/** `updateUser` (ADMIN) — role, display name, block/unblock (ТЗ ¶196, ¶197). Every field
 * optional. `409 SELF_MODIFICATION_FORBIDDEN`/`LAST_ADMIN_REQUIRED` guard self and the last
 * active admin. */
export function updateUser(userId: string, body: UserUpdateRequest): Promise<UserAccountI4> {
  return apiFetch(`/admin/users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify(body) });
}

/** `resetUserPassword` (ADMIN) — `204`, never echoes the new password back. */
export function resetUserPassword(userId: string, body: PasswordResetRequest): Promise<void> {
  return apiFetch(`/admin/users/${encodeURIComponent(userId)}/password`, { method: 'POST', body: JSON.stringify(body) });
}

/** `listAuditLog` (ADMIN) — ТЗ ¶205, ¶296. Filters by user, action and period; paged, newest
 * first. */
export function listAuditLog(
  params: {
    userId?: string;
    action?: AuditAction;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
    /** (I7 E43) «Только с изменениями». */
    withChanges?: boolean;
  } = {},
): Promise<{ items: AuditEntryView[]; total: number }> {
  const query = new URLSearchParams();
  if (params.withChanges) query.set('with_changes', 'true');
  if (params.userId) query.set('user_id', params.userId);
  if (params.action) query.set('action', params.action);
  if (params.from) query.set('from', params.from);
  if (params.to) query.set('to', params.to);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  const qs = query.toString();
  return apiFetch(`/admin/audit-log${qs ? `?${qs}` : ''}`);
}

/** `getUsageStats` (ADMIN) — ТЗ ¶206; per-day counts over an optional period (defaults to the
 * server's own 30-day window). */
export function getUsageStats(params: { from?: string; to?: string } = {}): Promise<UsageStats> {
  const query = new URLSearchParams();
  if (params.from) query.set('from', params.from);
  if (params.to) query.set('to', params.to);
  const qs = query.toString();
  return apiFetch(`/admin/usage-stats${qs ? `?${qs}` : ''}`);
}

/** `getServerLoad` (ADMIN) — ТЗ ¶208, ¶289. Every metric is `null`, never `0`, when it cannot be
 * read (SPEC §27 rule) — the caller renders «нет данных» for a `null`, never a bare `0`. */
export function getServerLoad(): Promise<ServerLoad> {
  return apiFetch('/admin/server-load');
}

/** `getErrorReport` (ADMIN) — ТЗ ¶207; merges backend error logs, `MODEL_ERROR` events and FATAL
 * transitions over an optional period, newest first. */
export function getErrorReport(params: { from?: string; to?: string; limit?: number } = {}): Promise<{ items: ErrorRecordView[] }> {
  const query = new URLSearchParams();
  if (params.from) query.set('from', params.from);
  if (params.to) query.set('to', params.to);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  const qs = query.toString();
  return apiFetch(`/admin/errors${qs ? `?${qs}` : ''}`);
}

/** `listAdminAlerts` (ADMIN) — ТЗ ¶308; derived, not stored (a stale/failed backup, an
 * `INFERENCE_FATAL` latch, repeated login failures). An empty list means nothing to report. */
export function listAdminAlerts(): Promise<{ items: AdminAlertView[] }> {
  return apiFetch('/admin/alerts');
}

/** `getBackupStatus` (ADMIN) — ТЗ ¶143, ¶216; `available: false` when `backups/last.json` is
 * absent or unreadable. */
export function getBackupStatus(): Promise<BackupStatus> {
  return apiFetch('/admin/backup-status');
}

// --- I5 E38: «сдал / не сдал» — configurable pass criteria (Q-E9b-3 variant г) ----------------
export type PassCriteriaRequest = components['schemas']['PassCriteriaRequest'];
export type PassCriteriaView = components['schemas']['PassCriteriaView'];
export type PassCriterion = components['schemas']['PassCriterion'];
export type PassVerdictView = components['schemas']['PassVerdictView'];

// --- I5 E37: admin read audit, profile JSON export, settings XML export (Q-E14-1, Q-E16-4,
// Q-E16-1) — the audit itself is server-side (E25's middleware); this section is the two new
// downloads' typed wrappers.

/** A file download as a `Blob` for a caller-chosen `Accept` (CSV, XLSX, PDF, JSON, XML — see the
 * I7 E46b exports above and the E37 downloads below) — fetched directly because {@link apiFetch}
 * assumes JSON *parsed*, not JSON *as a file*. Throws {@link ProblemError} on a problem+json
 * answer. */
async function fetchFile(path: string, accept: string): Promise<Blob> {
  const headers: Record<string, string> = { Accept: `${accept}, application/problem+json` };
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_BASE_PATH}${path}`, { headers });
  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    if (contentType.includes('application/problem+json')) {
      const problem = (await response.json()) as ProblemDetails;
      throw new ProblemError(problem, response.status);
    }
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return await response.blob();
}

/** `exportUserProfile` (Q-E16-4, ТЗ ¶363) — one account's profile as JSON (id, username, display
 * name, role, is_active, created_at, plus the E33 history summary for a TRAINEE), never the
 * password hash or SIP HA1. Allowed for the account itself and ADMIN — anyone else gets
 * `403 FORBIDDEN_FOR_ROLE`. */
export function exportUserProfile(userId: string): Promise<Blob> {
  return fetchFile(`/users/${encodeURIComponent(userId)}/profile-export`, 'application/json');
}

/** `exportSettingsXml` (Q-E16-1) — ADMIN only; the effective non-secret settings as XML. Every
 * secret (passwords, keys, tokens, the JWT secret, DB URLs with credentials) is omitted entirely.
 * Import is CLI only (`make settings-import`) — there is no matching upload here. */
export function exportSettingsXml(): Promise<Blob> {
  return fetchFile('/admin/settings/export', 'application/xml');
}

// --- I7 E43: «было → стало» in the audit journal (Q-E15-3) — `AuditEntryView.changes` items;
// `listAuditLog`'s `withChanges` filter is above. ---
export type AuditChangeView = components['schemas']['AuditChangeView'];

// --- I7 E53: scenario categories (G13), «Скачать» a scenario version (G14a) ---
export type ScenarioCategory = components['schemas']['ScenarioCategory'];
export type ScenarioDocumentFormat = 'yaml' | 'json';

/** `getScenarioVersionDocument` (I7 E53, G14a) — INSTRUCTOR / ADMIN; the stored version as a
 * YAML (default) or JSON file that uploads back through {@link importScenarioVersion}. */
export function getScenarioVersionDocument(
  scenarioVersionId: string,
  format: ScenarioDocumentFormat = 'yaml',
): Promise<Blob> {
  const query = format === 'yaml' ? '' : `?format=${format}`;
  return fetchFile(
    `/scenarios/versions/${encodeURIComponent(scenarioVersionId)}/document${query}`,
    format === 'yaml' ? 'application/yaml' : 'application/json',
  );
}
