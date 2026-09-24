// Draft-string <-> `FactValue` conversion for the single-value card controls (TEXT, TEXTAREA,
// NUMBER, PHONE, SELECT, CHECKBOX). Carried over from the pre-v2 `card-form.tsx` unchanged in
// meaning — an `<input>`/`<select>` always holds a string, so this is the one place that turns it
// back into the typed value `setCardField` sends (D12 design decision #2: the command carries the
// trainee's own edit, nothing derived).
import type { CardFieldSpec, FactValue } from '@/entities/card';

export function toDraftString(spec: CardFieldSpec, value: FactValue | undefined): string {
  if (spec.value_type === 'BOOLEAN') {
    return value === true ? 'true' : 'false';
  }
  if (value === undefined || value === null) {
    return '';
  }
  return String(value);
}

export function fromDraftString(spec: CardFieldSpec, draft: string): FactValue {
  switch (spec.value_type) {
    case 'BOOLEAN':
      return draft === 'true';
    case 'INTEGER': {
      if (draft.trim() === '') return null;
      const parsed = Number(draft);
      return Number.isNaN(parsed) ? null : Math.trunc(parsed);
    }
    case 'FLOAT': {
      if (draft.trim() === '') return null;
      const parsed = Number(draft);
      return Number.isNaN(parsed) ? null : parsed;
    }
    default:
      return draft;
  }
}
