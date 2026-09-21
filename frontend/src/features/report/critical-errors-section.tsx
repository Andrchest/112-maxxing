// §29 item 3: critical errors. Renders `score_report.critical_errors` verbatim — a rule already
// flagged `critical_failure` by the backend, never re-derived here.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { ScoreResultView } from '@/shared/api';

interface CriticalErrorsSectionProps {
  criticalErrors: readonly ScoreResultView[];
}

export function CriticalErrorsSection({ criticalErrors }: CriticalErrorsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportCriticalErrorsTitle')}</h2>
      </CardHeader>
      <CardContent>
        {criticalErrors.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportCriticalErrorsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {criticalErrors.map((result) => (
              <li key={result.rule_id} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <Badge variant="destructive">{t('reportEvidenceCriticalBadge')}</Badge>
                  <span className="text-sm font-medium">{result.name_ru}</span>
                </div>
                <p className="text-xs text-muted-foreground">{result.description_ru}</p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
