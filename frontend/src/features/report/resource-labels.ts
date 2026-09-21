// Exhaustive `ResourceStatus -> ru.ts key` table for the resource timeline (§29 item 12) — the
// report's own copy of `features/dds/dds-labels.ts`'s `RESOURCE_STATUS_LABEL_KEY` (same
// duplication-over-cross-feature-import treatment as `snapshot-card-fields.ts`).
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ResourceStatus } from '@/shared/api';

const RESOURCE_STATUS_LABEL_KEY: Record<ResourceStatus, keyof typeof ru> = {
  AVAILABLE: 'resourceStatusAvailable',
  SELECTED: 'resourceStatusSelected',
  DISPATCHED: 'resourceStatusDispatched',
  EN_ROUTE: 'resourceStatusEnRoute',
  ON_SCENE: 'resourceStatusOnScene',
  WORKING: 'resourceStatusWorking',
  RETURNING: 'resourceStatusReturning',
  OUT_OF_SERVICE: 'resourceStatusOutOfService',
  UNAVAILABLE: 'resourceStatusUnavailable',
};

export function resourceStatusLabelRu(value: ResourceStatus): string {
  return t(RESOURCE_STATUS_LABEL_KEY[value]);
}
