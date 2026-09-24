// Groups `CardFieldSpec[]` for the card form (SPEC §9: "rendered from the server's field specs,
// grouped"). The group key is the `field_path` prefix before the first dot (`address.house` ->
// `address`) — structural, derived from the server's own dotted path convention
// (`10-domain-model.md` §10.6), never a hard-coded copy of the field list itself. Group order is
// the order fields first appear in `field_specs`, which is itself server-controlled.
import type { CardFieldSpec, FactValue } from './card-store';
import { isCardFieldVisible } from './card-condition';

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

// I3 E3b (HLD 70 §70.5.2/§70.5.3): a v2 schema names its own layout `group` and `order` on every
// field (`header`, `applicant`, `address`, …) — this groups by that explicit `group` when the
// server sent one, and only falls back to the `field_path` prefix `groupCardFields` uses for a
// plain v1 schema (whose fields all carry `group: null`, `card_schema.py` "a v1 document ... gets
// the neutral values"). Fields `visible_when` hides for the given `values` are dropped, exactly
// like `features/dds/card-schema-render.ts`'s `groupVisibleCardFields` (the two mirror each
// other's contract, not each other's code — E3b owns this copy, E3c owns that one).
export function groupVisibleCardFields(
  fieldSpecs: readonly CardFieldSpec[],
  values: Readonly<Record<string, FactValue>>,
): CardFieldGroup[] {
  const groups: { key: string; fields: { spec: CardFieldSpec; position: number }[] }[] = [];
  const indexByKey = new Map<string, number>();

  fieldSpecs.forEach((spec, position) => {
    if (!isCardFieldVisible(spec, values)) return;
    const key = spec.group ?? (spec.field_path.split('.')[0] ?? spec.field_path);
    let index = indexByKey.get(key);
    if (index === undefined) {
      index = groups.length;
      indexByKey.set(key, index);
      groups.push({ key, fields: [] });
    }
    groups[index]!.fields.push({ spec, position });
  });

  return groups.map((group) => ({
    key: group.key,
    fields: group.fields
      .slice()
      .sort((a, b) => (a.spec.order ?? a.position) - (b.spec.order ?? b.position))
      .map((entry) => entry.spec),
  }));
}
