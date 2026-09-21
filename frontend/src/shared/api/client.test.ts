import { describe, expect, it } from 'vitest';
import { problemMessageRu, type ProblemCode } from './client';

// The complete `ProblemCode` enum (docs/hld/openapi.yaml `components.schemas.ProblemCode`).
// `problemMessageRu`'s lookup table is `Record<ProblemCode, …>` (client.ts), so adding a member
// to the generated union without adding it there already fails `tsc`; this test additionally
// proves every one of them resolves to a non-empty Russian string at runtime.
const ALL_PROBLEM_CODES: readonly ProblemCode[] = [
  'UNAUTHENTICATED',
  'FORBIDDEN_FOR_ROLE',
  'NOT_FOUND',
  'VALIDATION_ERROR',
  'INVALID_TRANSITION',
  'ACTION_NOT_AVAILABLE',
  'PARTICIPANT_NOT_ASSIGNED',
  'INFERENCE_NOT_READY',
  'SCENARIO_INVALID',
  'SCENARIO_VERSION_LOCKED',
  'SCENARIO_VERSION_EXISTS',
  'PREFAB_HANDOFF_REQUIRED',
  'RECIPIENT_SERVICES_EMPTY',
  'HANDOFF_ALREADY_CREATED',
  'CARD_FIELD_UNKNOWN',
  'CARD_VALUE_TYPE_MISMATCH',
  'RESOURCE_UNAVAILABLE',
  'SESSION_NOT_ACTIVE',
  'REPORT_NOT_READY',
  'REPORT_NOT_RELEASED',
  'EXPLANATION_ALREADY_EXISTS',
  'LLM_UNAVAILABLE',
  'AUDIO_PURGED',
  'RANGE_NOT_SATISFIABLE',
];

describe('problemMessageRu', () => {
  it.each(ALL_PROBLEM_CODES)('resolves a non-empty Russian message for %s', (code) => {
    expect(problemMessageRu(code)).toBeTypeOf('string');
    expect(problemMessageRu(code).length).toBeGreaterThan(0);
  });

  it('resolves a distinct message per code (no two codes share a placeholder string)', () => {
    const messages = ALL_PROBLEM_CODES.map((code) => problemMessageRu(code));
    expect(new Set(messages).size).toBe(ALL_PROBLEM_CODES.length);
  });
});
