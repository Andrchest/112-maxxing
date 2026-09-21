// §29 item 9: ground-truth vs entered-card diff (D11: "the one place WorldTruth is shown to a
// human"). Rendered only when the API returned entries — an empty array means the viewer may not
// see it (R3) or the session has no comparable facts (DDS-only session), not an error. This is the
// ONE report file allowed to touch a truth-vs-card-diff type (R11) — no other file under
// features/report imports `TruthVsCardDiffEntry`/`TruthVsCardDiffVerdict`.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { TruthVsCardDiffEntry, TruthVsCardDiffVerdict } from '@/shared/api';

const VERDICT_LABEL_KEY: Record<TruthVsCardDiffVerdict, keyof typeof ru> = {
  MATCH: 'truthDiffVerdictMatch',
  MISMATCH: 'truthDiffVerdictMismatch',
  MISSING: 'truthDiffVerdictMissing',
  NOT_COMPARABLE: 'truthDiffVerdictNotComparable',
};

const VERDICT_BADGE_VARIANT: Record<TruthVsCardDiffVerdict, 'default' | 'destructive' | 'outline'> = {
  MATCH: 'default',
  MISMATCH: 'destructive',
  MISSING: 'destructive',
  NOT_COMPARABLE: 'outline',
};

interface TruthDiffSectionProps {
  entries: readonly TruthVsCardDiffEntry[];
}

export function TruthDiffSection({ entries }: TruthDiffSectionProps) {
  if (entries.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportTruthDiffTitle')}</h2>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-2">
          {entries.map((entry) => (
            <li key={entry.field_path} className="flex flex-col gap-1 rounded-md border border-border p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{entry.label_ru}</span>
                <Badge variant={VERDICT_BADGE_VARIANT[entry.verdict]}>{t(VERDICT_LABEL_KEY[entry.verdict])}</Badge>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>
                  {t('reportTruthDiffWorldValueLabel')}: {String(entry.world_value ?? t('factValueEmpty'))}
                </span>
                <span>
                  {t('reportTruthDiffCardValueLabel')}: {String(entry.card_value ?? t('factValueEmpty'))}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
