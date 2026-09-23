// Handoff snapshot panel (SPEC §10; D3; R4). `handoff` is `null` before the operator hands the
// call off (or a DDS-only `SINGLE_ROLE` session, which is built from `prefab_handoff` instead — see
// `handoff.tsx`'s empty state either way), same treatment `features/report/handoff-section.tsx`
// uses. Labels its fields from the live `card`'s `field_specs` when available (the snapshot itself
// carries no labels) — falling back to the raw `field_path` when the card is absent or no longer
// carries that spec, never a guessed label.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { HandoffSnapshotView, OperatorCardView } from '@/shared/api';
import { serviceTypeLabelRu } from './instructor-labels';
import { formatFactValueRu, formatRawFactValueRu } from './format-fact-value';

interface HandoffSnapshotSectionProps {
  handoff: HandoffSnapshotView | null;
  card: OperatorCardView | null;
}

export function HandoffSnapshotSection({ handoff, card }: HandoffSnapshotSectionProps) {
  if (!handoff) {
    return (
      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">{t('reportHandoffTitle')}</h2>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t('reportHandoffEmpty')}</p>
        </CardContent>
      </Card>
    );
  }

  const specByPath = new Map((card?.field_specs ?? []).map((spec) => [spec.field_path, spec]));

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportHandoffTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('reportHandoffRecipientsLabel')}</span>
          {handoff.recipient_services.map((service) => (
            <Badge key={service} variant="outline">
              {serviceTypeLabelRu(service)}
            </Badge>
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            {t('reportHandoffCreatedAtLabel')}: {formatCallDurationMs(handoff.created_at_offset_ms)}
          </span>
        </div>
        <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {Object.keys(handoff.card_values)
            .sort()
            .map((fieldPath) => {
              const spec = specByPath.get(fieldPath);
              return (
                <div key={fieldPath} className="flex flex-col gap-0.5">
                  <dt className="text-xs text-muted-foreground">{spec?.label_ru ?? fieldPath}</dt>
                  <dd className="text-sm">
                    {spec ? formatFactValueRu(spec, handoff.card_values[fieldPath]) : formatRawFactValueRu(handoff.card_values[fieldPath])}
                  </dd>
                </div>
              );
            })}
        </dl>
      </CardContent>
    </Card>
  );
}
