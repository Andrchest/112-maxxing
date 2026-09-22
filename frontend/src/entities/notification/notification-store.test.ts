import { afterEach, describe, expect, it } from 'vitest';
import { useNotificationStore, countUnacknowledged, type NotificationView } from './notification-store';

function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    notification_id: 'notif-1',
    incident_id: 'inc-1',
    audience_role: 'DDS',
    severity: 'INFO',
    title_ru: 't',
    body_ru: 'b',
    created_at_offset_ms: 0,
    acknowledged_at_offset_ms: null,
    ...overrides,
  };
}

describe('useNotificationStore', () => {
  afterEach(() => {
    useNotificationStore.getState().reset();
  });

  it('setNotifications replaces the list wholesale', () => {
    useNotificationStore.getState().setNotifications([makeNotification()]);
    expect(useNotificationStore.getState().items).toHaveLength(1);
  });
});

describe('countUnacknowledged', () => {
  it('counts only items with acknowledged_at_offset_ms === null', () => {
    const items = [makeNotification({ notification_id: 'a' }), makeNotification({ notification_id: 'b', acknowledged_at_offset_ms: 1000 })];
    expect(countUnacknowledged(items)).toBe(1);
  });
});
