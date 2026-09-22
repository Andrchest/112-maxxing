// Pure reducer: folds one realtime `SessionEventEnvelope` onto the current notification list
// (`docs/hld/10-domain-model.md` §10.13 payload catalog). `NOTIFICATION_CREATED`'s payload lacks
// `incident_id` (`NotificationView` requires it) — `incidentId` is passed in as context, the one
// already-known value in the caller's own state (the session's own incident), not a fabricated
// fact (SPEC §10, §42 test 3 is about WorldTruth/CallerBelief facts, not this bookkeeping id).
//
// INV 3: `source_world_event_id` is neither read from the payload nor stored. The WS path
// redacts it for trainees and `NotificationView` no longer carries it; see
// `features/dds/no-world-truth-guard.test.ts`.
//
// Idempotent by `notification_id` on create (a duplicate delivery is a no-op) and by absolute
// overwrite on acknowledge — matching `entities/card`'s `applyCardEvent` convergence pattern.
import type { NotificationView } from './notification-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
type NotificationSeverity = components['schemas']['NotificationSeverity'];
type RoleType = components['schemas']['RoleType'];

interface NotificationCreatedPayload {
  notification_id: string;
  audience_role: RoleType;
  severity: NotificationSeverity;
  title_ru: string;
  body_ru: string;
  at_offset_ms: number;
}
interface NotificationAcknowledgedPayload {
  notification_id: string;
  at_offset_ms: number;
}

export interface ApplyNotificationEventContext {
  incidentId: string;
}

/** Folds one event onto `previous`. Newest-first, matching `listNotifications`' own order. */
export function applyNotificationEvent(
  previous: NotificationView[],
  event: SessionEventEnvelope,
  context: ApplyNotificationEventContext,
): NotificationView[] {
  switch (event.event_type) {
    case 'NOTIFICATION_CREATED': {
      const payload = event.payload as unknown as NotificationCreatedPayload;
      if (previous.some((item) => item.notification_id === payload.notification_id)) {
        return previous;
      }
      const created: NotificationView = {
        notification_id: payload.notification_id,
        incident_id: context.incidentId,
        audience_role: payload.audience_role,
        severity: payload.severity,
        title_ru: payload.title_ru,
        body_ru: payload.body_ru,
        created_at_offset_ms: payload.at_offset_ms,
        acknowledged_at_offset_ms: null,
      };
      return [created, ...previous];
    }
    case 'NOTIFICATION_ACKNOWLEDGED': {
      const payload = event.payload as unknown as NotificationAcknowledgedPayload;
      const index = previous.findIndex((item) => item.notification_id === payload.notification_id);
      if (index === -1) return previous;
      const next = previous.slice();
      next[index] = { ...next[index]!, acknowledged_at_offset_ms: payload.at_offset_ms };
      return next;
    }
    default:
      return previous;
  }
}
