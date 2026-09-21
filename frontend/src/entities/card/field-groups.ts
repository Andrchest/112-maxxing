// Groups `CardFieldSpec[]` for the card form (SPEC §9: "rendered from the server's field specs,
// grouped"). The group key is the `field_path` prefix before the first dot (`address.house` ->
// `address`) — structural, derived from the server's own dotted path convention
// (`10-domain-model.md` §10.6), never a hard-coded copy of the field list itself. Group order is
// the order fields first appear in `field_specs`, which is itself server-controlled.
import type { CardFieldSpec } from './card-store';

export interface CardFieldGroup {
  key: string;
  fields: CardFieldSpec[];
}

export function groupCardFields(fieldSpecs: readonly CardFieldSpec[]): CardFieldGroup[] {
  const groups: CardFieldGroup[] = [];
  const indexByKey = new Map<string, number>();

  for (const spec of fieldSpecs) {
    const key = spec.field_path.split('.')[0] ?? spec.field_path;
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, groups.length);
      groups.push({ key, fields: [spec] });
    } else {
      groups[existingIndex]!.fields.push(spec);
    }
  }

  return groups;
}
