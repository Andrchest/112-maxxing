// Entity: the service catalog («СЛУЖБЫ 112», `reference/services/v1.yaml`; HLD 70 §70.6.3, D18).
// A service is a catalog id, not a member of a closed enum, so its Russian name is catalog data:
// `serviceLabelRu` looks the id up here. Fed ONLY by server data — `listReferenceServices` with
// `include_hidden` (so a deprecated id in an old log still gets its name), loaded once per signed-in
// app by `ServiceCatalogLoader`.
//
// Before the catalog has arrived (first paint, a unit test that never loads it) the six legacy ids
// keep the labels they have always had, from `ru.ts` — the same text as their catalog `name_ru` —
// so nothing that rendered them before E2a renders differently. Any other unknown id renders raw.
import { create } from 'zustand';
import { t } from '@/shared/i18n';
import type { ru } from '@/shared/i18n/ru';
import type { ServiceCatalogEntry, ServiceId } from '@/shared/api';

/** The six ids of the former closed enum, verbatim and in its order — the first six catalog
 * entries. Until E2b's catalog picker, they are also what the services panel offers. */
export const LEGACY_SERVICE_IDS: readonly ServiceId[] = [
  'FIRE_RESCUE',
  'POLICE',
  'AMBULANCE',
  'GAS_SERVICE',
  'UTILITY_EMERGENCY',
  'EDDS',
];

/** The legacy ids' labels before the catalog loads (a fallback, not an exhaustive map). */
const LEGACY_SERVICE_LABEL_KEYS: Readonly<Record<string, keyof typeof ru>> = {
  FIRE_RESCUE: 'serviceTypeFireRescue',
  POLICE: 'serviceTypePolice',
  AMBULANCE: 'serviceTypeAmbulance',
  GAS_SERVICE: 'serviceTypeGasService',
  UTILITY_EMERGENCY: 'serviceTypeUtilityEmergency',
  EDDS: 'serviceTypeEdds',
};

interface ServiceCatalogState {
  /** Catalog entries by id; empty until the first `listReferenceServices` answer. */
  entries: Readonly<Record<string, ServiceCatalogEntry>>;
  loaded: boolean;
  /** Replaces the catalog wholesale with the server's list. */
  setEntries: (entries: readonly ServiceCatalogEntry[]) => void;
  reset: () => void;
}

export const useServiceCatalogStore = create<ServiceCatalogState>((set) => ({
  entries: {},
  loaded: false,
  setEntries: (entries) =>
    set({ entries: Object.fromEntries(entries.map((entry) => [entry.id, entry])), loaded: true }),
  reset: () => set({ entries: {}, loaded: false }),
}));

/** The Russian name of a service: its catalog `name_ru`; before the catalog loads, a legacy id's
 * `ru.ts` label; otherwise the raw id (never a blank label). */
export function serviceLabelRu(serviceId: ServiceId): string {
  const entry = useServiceCatalogStore.getState().entries[serviceId];
  if (entry) {
    return entry.name_ru;
  }
  const legacyKey = LEGACY_SERVICE_LABEL_KEYS[serviceId];
  return legacyKey ? t(legacyKey) : serviceId;
}
