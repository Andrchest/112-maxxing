import { describe, expect, it } from 'vitest';
import { loginThrottledMessageRu, problemMessageRu, type ProblemCode } from './client';

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
  'VARIANT_NOT_SUPPORTED',
  'VARIANT_NOT_AVAILABLE',
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

// I7 E51 (G5, ТЗ ¶295): the login page's throttled message carries the wait time the backend
// puts on `retry_after_s`, distinct from the generic `problemLoginThrottled` fallback.
describe('loginThrottledMessageRu', () => {
  it('interpolates the wait time from retry_after_s', () => {
    const message = loginThrottledMessageRu({
      title: 'Too Many Requests',
      status: 429,
      code: 'LOGIN_THROTTLED',
      retry_after_s: 10,
    });

    expect(message).toContain('10');
    expect(message).not.toBe(problemMessageRu('LOGIN_THROTTLED'));
  });

  it.each([undefined, 0, -5, Number.NaN, 'not-a-number'])(
    'falls back to the generic message when retry_after_s is %s',
    (retryAfterS) => {
      const message = loginThrottledMessageRu({
        title: 'Too Many Requests',
        status: 429,
        code: 'LOGIN_THROTTLED',
        retry_after_s: retryAfterS,
      });

      expect(message).toBe(problemMessageRu('LOGIN_THROTTLED'));
    },
  );
});
