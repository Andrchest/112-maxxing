import { describe, expect, it } from 'vitest';
import { formatDurationMs, remainingDeadlineMs } from './incident-countdown';

describe('remainingDeadlineMs', () => {
  it('returns null when the deadline offset is null (not applicable yet)', () => {
    expect(remainingDeadlineMs(null, 1000, 0)).toBeNull();
  });

  it('subtracts the session offset and elapsed wall time from the deadline offset', () => {
    expect(remainingDeadlineMs(30000, 5000, 2000)).toBe(23000);
  });

  it('goes negative once the deadline has passed', () => {
    expect(remainingDeadlineMs(30000, 29000, 2000)).toBe(-1000);
  });
});

describe('formatDurationMs', () => {
  it('formats under an hour as mm:ss', () => {
    expect(formatDurationMs(0)).toBe('00:00');
    expect(formatDurationMs(59000)).toBe('00:59');
    expect(formatDurationMs(65000)).toBe('01:05');
  });

  it('formats an hour or more as h:mm:ss', () => {
    expect(formatDurationMs(3661000)).toBe('1:01:01');
  });

  it('clamps a negative duration to zero', () => {
    expect(formatDurationMs(-5000)).toBe('00:00');
  });
});
