// «Грамотность и адреса» (I4 E35, 71 §71.12, D35) — report-time, read-only annotation of the
// texts the trainee typed; no score effect (Q-E11-1 open). `available: false` renders the
// server's own `unavailable_message_ru` verbatim (SPEC §27's honesty rule: never «0 ошибок» —
// the section never claims "no misspellings" when the checker did not run at all). `available:
// true` with nothing flagged renders «Замечаний нет», never an empty list.
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { flaggedTextQualityItems } from '@/entities/text-quality';
import type { TextQualityReportView } from '@/shared/api';

interface TextQualitySectionProps {
  textQuality: TextQualityReportView;
}

export function TextQualitySection({ textQuality }: TextQualitySectionProps) {
  const items = flaggedTextQualityItems(textQuality);
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('textQualitySectionTitle')}</h2>
      </CardHeader>
      <CardContent>
        {!textQuality.available ? (
          <p className="text-sm text-muted-foreground" data-slot="text-quality-unavailable">
            {textQuality.unavailable_message_ru}
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-slot="text-quality-none-flagged">
            {t('textQualityNoneFlagged')}
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm" data-slot="text-quality-flagged-list">
            {items.map((item) => (
              <li key={item.key} className="flex flex-col gap-0.5 rounded-md border border-border p-2" data-slot="text-quality-flagged-item">
                <span className="text-xs text-muted-foreground">{item.fieldLabel}</span>
                <span>{item.message}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
