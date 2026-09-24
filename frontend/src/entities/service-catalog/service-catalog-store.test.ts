// The service catalog lookup (I3 E2a, HLD 70 §70.6.3, D18): the six legacy ids keep exactly the
// labels they rendered before E2a, before and after the catalog loads; any other catalog id is
// named by the catalog; an id the catalog does not know renders raw, never blank.
import { afterEach, describe, expect, it } from 'vitest';
import { ru } from '@/shared/i18n/ru';
import type { ServiceCatalogEntry } from '@/shared/api';
import { LEGACY_SERVICE_IDS, serviceLabelRu, useServiceCatalogStore } from './service-catalog-store';

const LEGACY_LABELS: Readonly<Record<string, string>> = {
  FIRE_RESCUE: ru.serviceTypeFireRescue,
  POLICE: ru.serviceTypePolice,
  AMBULANCE: ru.serviceTypeAmbulance,
  GAS_SERVICE: ru.serviceTypeGasService,
  UTILITY_EMERGENCY: ru.serviceTypeUtilityEmergency,
  EDDS: ru.serviceTypeEdds,
};

function entry(id: string, nameRu: string): ServiceCatalogEntry {
  return {
    id,
    name_ru: nameRu,
    full_name_ru: nameRu,
    kind: 'CITY',
    code: null,
    okrug: null,
    district: null,
    classifier_org_id: null,
    status_policy: 'DEFAULT',
    display: true,
    deprecated: false,
    phone: null,
  };
}

describe('serviceLabelRu', () => {
  afterEach(() => useServiceCatalogStore.getState().reset());

  it('names the six legacy ids exactly as before, without a loaded catalog', () => {
    expect(LEGACY_SERVICE_IDS).toEqual(Object.keys(LEGACY_LABELS));
    for (const id of LEGACY_SERVICE_IDS) {
      expect(serviceLabelRu(id)).toBe(LEGACY_LABELS[id]);
    }
  });

  it('names a catalog id from the catalog once it is loaded', () => {
    useServiceCatalogStore.getState().setEntries([
      ...LEGACY_SERVICE_IDS.map((id) => entry(id, LEGACY_LABELS[id] ?? id)),
      entry('MOSVODOKANAL', 'Mosvodokanal-name'),
    ]);
    expect(useServiceCatalogStore.getState().loaded).toBe(true);
    expect(serviceLabelRu('MOSVODOKANAL')).toBe('Mosvodokanal-name');
    for (const id of LEGACY_SERVICE_IDS) {
      expect(serviceLabelRu(id)).toBe(LEGACY_LABELS[id]);
    }
  });

  it('renders an unknown id raw rather than blank', () => {
    expect(serviceLabelRu('NOT_IN_THE_CATALOG')).toBe('NOT_IN_THE_CATALOG');
  });
});
