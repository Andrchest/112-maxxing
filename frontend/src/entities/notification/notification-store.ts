// Entity: DDS/Operator 112 notifications (`docs/hld/10-domain-model.md` §10.7 `Notification`;
// D5, D12). `listNotifications` is one endpoint shared by both consoles (the backend filters by
// `audience_role == caller's role`); this store is role-agnostic for the same reason. Fed ONLY by
// server data — `listNotifications`, and the `NOTIFICATION_CREATED`/`NOTIFICATION_ACKNOWLEDGED` WS
// event fold in `apply-notification-event.ts`.
import { create } from 'zustand';
import type { components } from '@/shared/api';

export type NotificationView = components['schemas']['NotificationView'];
export type NotificationSeverity = components['schemas']['NotificationSeverity'];

interface NotificationStoreState {
  items: NotificationView[];
  /** Replaces the list wholesale with the server's latest `listNotifications` page. */
  setNotifications: (items: NotificationView[]) => void;
  reset: () => void;
}

export const useNotificationStore = create<NotificationStoreState>((set) => ({
  items: [],
  setNotifications: (items) => set({ items }),
  reset: () => set({ items: [] }),
}));

/** The count the badge renders — a plain filter over the server's own items (`acknowledged_at_offset_ms
 * === null`), not a client-derived fact: every item counted was sent by the server exactly as
 * shown. */
export function countUnacknowledged(items: readonly NotificationView[]): number {
  return items.filter((item) => item.acknowledged_at_offset_ms === null).length;
}
