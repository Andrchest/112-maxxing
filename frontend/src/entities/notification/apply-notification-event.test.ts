import { describe, expect, it } from 'vitest';
import { applyNotificationEvent } from './apply-notification-event';
import type { NotificationView } from './notification-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    notification_id: 'notif-1',
    incident_id: 'inc-1',
    audience_role: 'DDS',
    severity: 'WARNING',
    title_ru: 'Пожар распространяется',
    body_ru: 'Огонь перешёл на соседнее помещение.',
    created_at_offset_ms: 1000,
    acknowledged_at_offset_ms: null,
    ...overrides,
  };
}

function makeEvent(overrides: Partial<SessionEventEnvelope> = {}): SessionEventEnvelope {
  return {
    seq_no: 9,
    event_type: 'NOTIFICATION_CREATED',
    timestamp_utc: '2026-09-21T10:00:00Z',
    monotonic_offset_ms: 5000,
    payload: {},
    ...overrides,
  };
}

const CTX = { incidentId: 'inc-1' };

describe('applyNotificationEvent', () => {
  it('NOTIFICATION_CREATED prepends a new notification (newest first)', () => {
    const previous = [makeNotification({ notification_id: 'notif-0' })];
    const next = applyNotificationEvent(
      previous,
      makeEvent({ payload: { notification_id: 'notif-1', audience_role: 'DDS', severity: 'CRITICAL', title_ru: 'Газовый баллон', body_ru: 'Обнаружен газовый баллон.', source_world_event_id: 'gas_cylinder_hazard', at_offset_ms: 5000 } }),
      CTX,
    );
    expect(next).toHaveLength(2);
    expect(next[0]?.notification_id).toBe('notif-1');
    expect(next[0]?.incident_id).toBe('inc-1');
    expect(next[0]?.acknowledged_at_offset_ms).toBeNull();
  });

  it('is idempotent by notification_id — a duplicate delivery is a no-op', () => {
    const previous = [makeNotification()];
    const next = applyNotificationEvent(
      previous,
      makeEvent({ payload: { notification_id: 'notif-1', audience_role: 'DDS', severity: 'WARNING', title_ru: 'x', body_ru: 'y', source_world_event_id: null, at_offset_ms: 1000 } }),
      CTX,
    );
    expect(next).toBe(previous);
  });

  it('NOTIFICATION_ACKNOWLEDGED patches acknowledged_at_offset_ms', () => {
    const previous = [makeNotification()];
    const next = applyNotificationEvent(
      previous,
      makeEvent({ event_type: 'NOTIFICATION_ACKNOWLEDGED', payload: { notification_id: 'notif-1', at_offset_ms: 6000, latency_ms: 1000, actor_user_id: 'u1' } }),
      CTX,
    );
    expect(next[0]?.acknowledged_at_offset_ms).toBe(6000);
  });

  it('ignores unrelated event types', () => {
    const previous = [makeNotification()];
    const next = applyNotificationEvent(previous, makeEvent({ event_type: 'RADIO_MESSAGE_CREATED', payload: {} }), CTX);
    expect(next).toBe(previous);
  });
});
