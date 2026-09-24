// The operator card form (SPEC §9: "the trainee manually edits the incident card"; D12 design
// decision #2). Rendered entirely from the server's `CardFieldSpec[]` — labels, groups, value
// types, options and `visible_when` are never retyped here. One `setCardField` command per field
// commit (D12 rule), a fresh `client_command_id` per command, no request when the value did not
// change, and a failed command restores the last server-confirmed value.
//
// I3 E3b (HLD 70 §70.5.2–§70.5.4, D17): a v2 card (its `field_specs` carry an explicit `group`,
// §70.5.2 — `group: 'header'` only ever appears on a v2 schema) renders the reference 1:1 layout
// through `CardFormV2` (`features/operator/card/**`); a v1 card (`group` always `null`) keeps the
// plain grouped-fields layout below, unchanged in meaning from before this epic ("v1 cards still
// render from `field_specs`", the E3b row of `90-tbd-epics.md`).
import { useCardStore, groupCardFields } from '@/entities/card';
import { useCallStateStore } from '@/entities/session';
import { useStageStore, hasAvailableAction } from '@/entities/stage';
import { t } from '@/shared/i18n';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { CardField } from './card/card-field';
import { CardFormV2 } from './card/card-form-v2';
import { groupLabelRu } from './card/group-labels';
import { useCardFieldCommit } from './card/use-card-field-commit';

interface CardFormProps {
  sessionId: string;
  /** `SessionDetail.monotonic_offset_ms` — the v2 header's `fill_within_ms` countdown ticks from
   * this, the same server-anchor idiom `PhoneWidget`'s call timer uses (D9). Unused by the v1
   * layout, which has no such timer. */
  monotonicOffsetMs?: number;
}

export function CardForm({ sessionId, monotonicOffsetMs }: CardFormProps) {
  const card = useCardStore((state) => state.card);
  const availableActions = useStageStore((state) => state.availableActions);
  const answeredAtOffsetMs = useCallStateStore((state) => state.callState?.answered_at_offset_ms ?? null);
  const canEdit = hasAvailableAction(availableActions, 'edit_card');
  const commitCardField = useCardFieldCommit(sessionId);

  if (!card) {
    return null;
  }

  // A v2 schema is the one that gives fields an explicit layout `group` (§70.5.2); v1 fields all
  // carry `group: null` (`card_schema.py`: "a v1 document ... gets the neutral values"), so this
  // never misreads a v1 card that merely happens to have a field named like a v2 group.
  const isV2 = card.field_specs.some((spec) => spec.group !== null && spec.group !== undefined);

  if (isV2) {
    return (
      <CardFormV2
        sessionId={sessionId}
        card={card}
        disabled={!canEdit}
        onCommit={commitCardField}
        answeredAtOffsetMs={answeredAtOffsetMs}
        monotonicOffsetMs={monotonicOffsetMs ?? 0}
      />
    );
  }

  // `recipients.services` is edited only through the services panel (SPEC §9, `setCardField`'s
  // own contract) — excluded here so it is never rendered (and never committed) twice.
  const groups = groupCardFields(card.field_specs.filter((spec) => spec.field_path !== 'recipients.services'));

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorCardTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabelRu(group.key)}</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {group.fields.map((spec) => (
                <CardField key={spec.field_path} spec={spec} confirmedValue={card.values[spec.field_path]} disabled={!canEdit} onCommit={commitCardField} />
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
