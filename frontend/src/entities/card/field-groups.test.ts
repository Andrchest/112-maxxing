import { describe, expect, it } from 'vitest';
import { groupCardFields } from './field-groups';
import type { CardFieldSpec } from './card-store';

function spec(fieldPath: string): CardFieldSpec {
  return {
    field_path: fieldPath,
    value_type: 'STRING',
    enum_name: null,
    label_ru: fieldPath,
    scoring_relevant: false,
    required_for_handoff: false,
  };
}

describe('groupCardFields', () => {
  it('groups by the field_path prefix, preserving first-seen order', () => {
    const groups = groupCardFields([
      spec('address.street'),
      spec('caller.phone'),
      spec('address.house'),
      spec('incident.type'),
    ]);

    expect(groups.map((g) => g.key)).toEqual(['address', 'caller', 'incident']);
    expect(groups[0]?.fields.map((f) => f.field_path)).toEqual(['address.street', 'address.house']);
  });

  it('does not retype or drop any field — every input spec appears exactly once', () => {
    const specs = [spec('a.one'), spec('a.two'), spec('b.one')];
    const groups = groupCardFields(specs);
    const flattened = groups.flatMap((g) => g.fields);
    expect(flattened).toEqual(specs);
  });
});
