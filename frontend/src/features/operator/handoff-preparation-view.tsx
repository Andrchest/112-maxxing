// The handoff-preparation view (SPEC §10). `beginHandoffPreparation` is "deliberately unguarded:
// an incomplete card must remain possible, because an omission must propagate to DDS as a real
// mistake" — so the missing-fields list here is an advisory hint, never a block (`CardFieldSpec.
// required_for_handoff` is itself documented as advisory only in `openapi.yaml`). The card itself
// stays the same `CardForm` (still `setCardField`-editable while `available_actions` allows it —
// `back_to_interview` exists precisely so the trainee can keep editing).
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { useCardStore } from '@/entities/card';
import { CardForm } from './card-form';

interface HandoffPreparationViewProps {
  sessionId: string;
  /** Threaded through to `CardForm` — the v2 header's `fill_within_ms` countdown ticks from this
   * (I3 E3b), same as the operator console's own `CardForm` render. */
  monotonicOffsetMs?: number;
}

export function HandoffPreparationView({ sessionId, monotonicOffsetMs }: HandoffPreparationViewProps) {
  const card = useCardStore((state) => state.card);
  const missingFields = (card?.field_specs ?? []).filter(
    (spec) => spec.required_for_handoff && card !== null && !(spec.field_path in card.values),
  );

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">{t('operatorHandoffPreparationTitle')}</h2>
        </CardHeader>
        {missingFields.length > 0 ? (
          <CardContent>
            <p className="text-sm text-amber-600" role="status">
              {t('operatorHandoffMissingFieldsTitle')}
            </p>
            <ul className="mt-1 list-disc pl-5 text-sm text-muted-foreground">
              {missingFields.map((spec) => (
                <li key={spec.field_path}>{spec.label_ru}</li>
              ))}
            </ul>
          </CardContent>
        ) : null}
      </Card>
      <CardForm sessionId={sessionId} monotonicOffsetMs={monotonicOffsetMs} />
    </div>
  );
}
