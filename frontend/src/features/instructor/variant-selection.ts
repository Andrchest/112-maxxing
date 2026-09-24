// The variant pickers' shared selection rules — `create-session-form.tsx` and
// `lesson-create-form.tsx` offer the same switches (70 §70.2) and must refuse the same values.
import type { ScenarioVariantsView, SessionVariants } from '@/shared/api';

export type VariantSwitch = keyof SessionVariants;

/** A value the scenario version supports (the server has already dropped unimplemented ones). */
export function isVariantSupported(view: ScenarioVariantsView, variantSwitch: VariantSwitch, value: string): boolean {
  return (view.supported[variantSwitch] as readonly string[]).includes(value);
}

/**
 * I4 E21 (D28, R41): the ДДС phone exists in memo mode only. Memo scenarios default it to `ON`, so
 * under `RESOURCE_PICKER` `ON` is offered disabled — the server answers `409
 * VARIANT_NOT_SUPPORTED` for picker + `ON`.
 */
export function isVariantSelectable(
  view: ScenarioVariantsView,
  variants: SessionVariants,
  variantSwitch: VariantSwitch,
  value: string,
): boolean {
  if (variantSwitch === 'dds_brigade_call' && value === 'ON' && variants.dds_mode === 'RESOURCE_PICKER') {
    return false;
  }
  return isVariantSupported(view, variantSwitch, value);
}

/** The variants with R41 applied: the picker has no phone, so `ON` becomes `OFF`. */
export function withoutPickerPhone(variants: SessionVariants): SessionVariants {
  return variants.dds_mode === 'RESOURCE_PICKER' && variants.dds_brigade_call === 'ON'
    ? { ...variants, dds_brigade_call: 'OFF' }
    : variants;
}
