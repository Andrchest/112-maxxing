// The v2 card layout (I3 E3b, HLD 70 §70.5.2–§70.5.4; ui-check D-3…D-7): header strip on top, an
// applicant/address/description column and an incident/questionnaire column below it, matching
// the reference's left/right layout (`screenshot-card112/image1.png`). The services bar (E2b′'s
// `ServicesPanel`) used to be embedded here at the bottom of this same column; I3 E7a (manager
// review) hoisted it to `console-page.tsx` instead, full page width and pinned to the true
// viewport bottom like the reference — this component no longer renders it (still renders
// `recipients.comment`, the one `services`-group field that isn't the panel's own).
import type { OperatorCardView } from '@/entities/card';
import { groupVisibleCardFields } from '@/entities/card';
import { FieldGroupSection, type FieldGroupLayout } from './field-group-section';
import { CardHeaderStrip } from './card-header-strip';
import { CardField } from './card-field';
import type { CommitCardField } from './use-card-field-commit';

interface CardFormV2Props {
  sessionId: string;
  card: OperatorCardView;
  disabled: boolean;
  onCommit: CommitCardField;
  answeredAtOffsetMs: number | null;
  monotonicOffsetMs: number;
}

const LEFT_COLUMN_GROUPS = ['applicant', 'address', 'description'];
const RIGHT_COLUMN_GROUPS = ['incident', 'q_fire', 'q_gas', 'q_explosion'];
const KNOWN_GROUPS = new Set(['header', 'flags', ...LEFT_COLUMN_GROUPS, ...RIGHT_COLUMN_GROUPS, 'services']);

// Manager review (I3 E3b): the applicant block is one inline row (gsi image1) and every
// questionnaire block is a label-left/control-right row grid (gsi image2's «Где» / «Признак
// пожара» / … rows) — address/description/incident keep the original two-column field grid.
const GROUP_LAYOUT: Record<string, FieldGroupLayout> = {
  applicant: 'inline',
  q_fire: 'row',
  q_gas: 'row',
  q_explosion: 'row',
};

export function CardFormV2({ sessionId, card, disabled, onCommit, answeredAtOffsetMs, monotonicOffsetMs }: CardFormV2Props) {
  // `recipients.services` is edited only through the services panel (SPEC §9, `setCardField`'s own
  // contract) — excluded here so it is never rendered (and never committed) twice.
  const specs = card.field_specs.filter((spec) => spec.field_path !== 'recipients.services');
  const groups = groupVisibleCardFields(specs, card.values);
  const byKey = new Map(groups.map((group) => [group.key, group.fields]));
  const otherGroups = groups.filter((group) => !KNOWN_GROUPS.has(group.key));
  // Everything left in the "services" group once `recipients.services` is excluded above
  // (`recipients.comment`, when the schema has it) — rendered under the services bar itself, not
  // in a second services block (manager review: no separate notification-list block).
  const serviceCommentFields = byKey.get('services') ?? [];

  return (
    <div className="flex flex-col gap-4">
      <CardHeaderStrip
        sessionId={sessionId}
        card={card}
        headerFields={byKey.get('header') ?? []}
        flagFields={byKey.get('flags') ?? []}
        disabled={disabled}
        onCommit={onCommit}
        answeredAtOffsetMs={answeredAtOffsetMs}
        monotonicOffsetMs={monotonicOffsetMs}
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          {LEFT_COLUMN_GROUPS.map((key) => (
            <FieldGroupSection key={key} groupKey={key} fields={byKey.get(key) ?? []} card={card} disabled={disabled} onCommit={onCommit} layout={GROUP_LAYOUT[key]} />
          ))}
        </div>
        <div className="flex flex-col gap-4">
          {RIGHT_COLUMN_GROUPS.map((key) => (
            <FieldGroupSection key={key} groupKey={key} fields={byKey.get(key) ?? []} card={card} disabled={disabled} onCommit={onCommit} layout={GROUP_LAYOUT[key]} />
          ))}
        </div>
      </div>
      {otherGroups.map((group) => (
        <FieldGroupSection key={group.key} groupKey={group.key} fields={group.fields} card={card} disabled={disabled} onCommit={onCommit} />
      ))}
      {/* `recipients.comment`, when the schema has it — the services bar itself now lives at the
          page level (`console-page.tsx`), not here (I3 E7a manager review). */}
      {serviceCommentFields.map((spec) => (
        <CardField key={spec.field_path} spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} />
      ))}
    </div>
  );
}
