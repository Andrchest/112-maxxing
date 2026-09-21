// Typed helpers over the generated OpenAPI schema (D12, D8). Every request/response shape here
// is derived from `operations[...]`/`components[...]` in `./schema.d.ts` — this file is the only
// place allowed to describe a REST call by its operationId; nothing hand-duplicates a generated
// DTO (see `src/app/no-duplicate-dto-guard.test.ts`).
import { apiFetch } from '@/shared/lib/api';
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

// -- E8-B: operator console (SPEC §9, §10, §32, §39; D3, D12) --------------------------------
// Additive to E8-A's client (client.ts is "the only place allowed to describe a REST call by its
// operationId", D12 design decision #1) — not in this task's original FILES list, but required by
// it: the console cannot call any `/operator/*` command without a typed wrapper here, and
// `no-duplicate-dto-guard.test.ts` already forbids re-declaring these shapes elsewhere.
export type SessionListItem = components['schemas']['SessionListItem'];
export type SessionState = components['schemas']['SessionState'];
export type SessionSnapshot = components['schemas']['SessionSnapshot'];
export type OperatorStageView = components['schemas']['OperatorStageView'];
export type OperatorCardView = components['schemas']['OperatorCardView'];
export type CardFieldSpec = components['schemas']['CardFieldSpec'];
export type FactValue = components['schemas']['FactValue'];
export type ServiceType = components['schemas']['ServiceType'];
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

export function answerCall(sessionId: string): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/call/answer`, { method: 'POST' });
}

export function endCall(sessionId: string, body: EndCallRequest): Promise<OperatorStageView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/call/end`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** Exactly one `field_path` per command (SPEC §9: every mutation stored with actor/previous/new
 * value). */
export function setCardField(sessionId: string, body: SetCardFieldRequest): Promise<SetCardFieldResponse> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/card/field`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function selectRecipientService(sessionId: string, serviceType: ServiceType): Promise<ServiceSelectionView> {
  return apiFetch(`/sessions/${encodeURIComponent(sessionId)}/operator/services/select`, {
    method: 'POST',
    body: JSON.stringify({ service_type: serviceType }),
  });
}

export function deselectRecipientService(sessionId: string, serviceType: ServiceType): Promise<ServiceSelectionView> {
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
};

/** Russian message for a backend `ProblemCode` (D12 design decision #5). Every UI surface that
 * catches a {@link ProblemError} renders `problem.detail`/`problem.title` for logging only and
 * this message for the trainee/instructor. */
export function problemMessageRu(code: ProblemCode): string {
  return ru[PROBLEM_MESSAGE_KEYS[code]];
}
