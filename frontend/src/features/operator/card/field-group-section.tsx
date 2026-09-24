// One titled block of the reference layout. Fields already carry the schema's own `order`
// (`groupVisibleCardFields`, `entities/card`); this only lays them out, in one of three shapes the
// reference itself uses per block (manager review, I3 E3b):
//   - "row" — the per-type questionnaire (q_fire/q_gas/q_explosion): label on the LEFT, the
//     control on the RIGHT, one field per row (gsi image2's «Где» / «Признак пожара» / … rows).
//   - "inline" — the applicant block: every field in one horizontal row, in schema order
//     («Фамилия и имя заявителя» | «Статус заявителя» | …, gsi image1).
//   - "grid" (default) — everything else (address, description, services' leftover fields): the
//     original two-column field grid, `TOGGLE_SET`/`CHIPS`/`TEXTAREA` spanning both columns.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Label } from '@/shared/ui/label';
import type { CardFieldSpec, OperatorCardView } from '@/entities/card';
import { CardField } from './card-field';
import { groupLabelRu } from './group-labels';
import type { CommitCardField } from './use-card-field-commit';

export type FieldGroupLayout = 'grid' | 'row' | 'inline';

interface FieldGroupSectionProps {
  groupKey: string;
  fields: readonly CardFieldSpec[];
  card: OperatorCardView;
  disabled: boolean;
  onCommit: CommitCardField;
  layout?: FieldGroupLayout;
}

function spansFullWidth(spec: CardFieldSpec): boolean {
  return spec.control === 'TOGGLE_SET' || spec.control === 'CHIPS' || spec.control === 'TEXTAREA';
}

export function FieldGroupSection({ groupKey, fields, card, disabled, onCommit, layout = 'grid' }: FieldGroupSectionProps) {
  if (fields.length === 0) {
    return null;
  }

  let body: React.ReactNode;
  if (layout === 'row') {
    body = (
      <div className="flex flex-col">
        {fields.map((spec) => (
          <div key={spec.field_path} className="grid grid-cols-[180px_1fr] items-start gap-3 border-b border-border/50 py-2 last:border-b-0">
            <Label className="pt-1">{spec.label_ru}</Label>
            <CardField spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} hideLabel />
          </div>
        ))}
      </div>
    );
  } else if (layout === 'inline') {
    body = (
      <div className="flex flex-wrap items-end gap-3">
        {fields.map((spec) => (
          <div key={spec.field_path} className="min-w-40 flex-1">
            <CardField spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} />
          </div>
        ))}
      </div>
    );
  } else {
    body = (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {fields.map((spec) => (
          <div key={spec.field_path} className={spansFullWidth(spec) ? 'sm:col-span-2' : undefined}>
            <CardField spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} />
          </div>
        ))}
      </div>
    );
  }

  // I3 E7a (D20, ui-check D-5; manager review): the reference's dark «Происшествие 101» banner
  // over the per-type questionnaire block — `bg-foreground text-background` reuses the same
  // dark-title-bar convention `features/dds/work-item-panel.tsx`'s `DARK_BAR_GROUPS` already
  // applies on the ДДС side (both read `--foreground`, which `.reference-light` sets to the
  // reference's own dark block-header colour, `src/index.css`). Every other group keeps the plain
  // muted label — the reference does not bar those. Normal case, not small-caps uppercase — the
  // reference's own bar text is title case.
  const isDarkBar = layout === 'row';

  return (
    <Card data-slot={`card-group-${groupKey}`}>
      <CardHeader className={isDarkBar ? 'rounded-t-xl bg-foreground py-2' : undefined}>
        <h3 className={isDarkBar ? 'text-sm font-semibold text-background' : 'text-xs font-semibold tracking-wide text-muted-foreground uppercase'}>
          {groupLabelRu(groupKey)}
        </h3>
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  );
}
