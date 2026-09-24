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

/** `GET /users` (additive, E7) — INSTRUCTOR/ADMIN only. `role` narrows to one `UserRole` (used
 * by E8-B's trainee picker to list only `TRAINEE` accounts). */
export function listUsers(params: { role?: UserRole } = {}): Promise<{ items: UserAccount[]; total: number }> {
  const query = new URLSearchParams();
  if (params.role) query.set('role', params.role);
  const qs = query.toString();
  return apiFetch(`/users${qs ? `?${qs}` : ''}`);
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

export function listScenarios(): Promise<{ items: ScenarioSummary[]; total: number }> {
  return apiFetch('/scenarios');
}

export function listScenarioVersions(
  scenarioId: string,
): Promise<{ items: ScenarioVersionListItem[]; total: number }> {
  return apiFetch(`/scenarios/${scenarioId}/versions`);
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
};

/** Russian message for a backend `ProblemCode` (D12 design decision #5). Every UI surface that
 * catches a {@link ProblemError} renders `problem.detail`/`problem.title` for logging only and
 * this message for the trainee/instructor. */
export function problemMessageRu(code: ProblemCode): string {
  return ru[PROBLEM_MESSAGE_KEYS[code]];
}
