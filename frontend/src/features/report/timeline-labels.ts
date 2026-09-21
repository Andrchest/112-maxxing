// Exhaustive `ActorType -> ru.ts key` table (D12 design decision #5) for the timeline's actor
// filter (SPEC §29 item 4). Event-type text itself is `summary_ru`, rendered by the backend
// (recon §5 item 1) — this file only labels who acted.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { ActorType } from '@/shared/api';

export const ACTOR_TYPE_LABEL_KEY: Record<ActorType, keyof typeof ru> = {
  TRAINEE: 'actorTypeTrainee',
  INSTRUCTOR: 'actorTypeInstructor',
  SIMULATION: 'actorTypeSimulation',
  MODEL: 'actorTypeModel',
  SYSTEM: 'actorTypeSystem',
};

export function actorTypeLabelRu(value: ActorType): string {
  return t(ACTOR_TYPE_LABEL_KEY[value]);
}
