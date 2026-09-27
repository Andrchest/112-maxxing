// I5 E38 (Q-E9b-3 variant г): the report header's «Сдал» / «Не сдал» and, when failed, which
// criteria did not hold — `SessionReport.pass_verdict` exactly as the server derived it from the
// stored score and the session's recorded criteria. Nothing is judged or summed here (D11,
// `no-score-math-guard.test.ts`). A report without a verdict renders nothing.
import { Badge } from '@/shared/ui/badge';
import { t } from '@/shared/i18n';
import { criteriaLines, failedCriteriaLines, passVerdictLabel } from '@/entities/pass-verdict';
import type { PassVerdictView } from '@/shared/api';

export function PassVerdictSection({ verdict }: { verdict: PassVerdictView | null | undefined }) {
  if (!verdict) return null;
  const failed = failedCriteriaLines(verdict);
  return (
    <section
      className="mt-3 flex flex-col gap-1 rounded-lg border border-border p-3 text-sm"
      data-slot="pass-verdict"
      data-passed={verdict.passed ? 'true' : 'false'}
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">{t('passVerdictTitle')}:</span>
        <Badge variant={verdict.passed ? 'default' : 'destructive'} data-slot="pass-verdict-label">
          {passVerdictLabel(verdict)}
        </Badge>
      </div>
      {failed.length > 0 ? (
        <ul className="flex flex-col gap-0.5 text-destructive" data-slot="pass-verdict-failed">
          {failed.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs text-muted-foreground" data-slot="pass-verdict-criteria">
        {t('passVerdictCriteriaLabel')}: {criteriaLines(verdict.criteria).join('; ')}
      </p>
    </section>
  );
}
