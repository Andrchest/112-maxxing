// The LLM explanation panel (SPEC §2/§26/§29/§41). Shown only below the deterministic scores
// (`report-page.tsx` places it last), generated only from an already-persisted `ScoreReport`
// (backend concern — this panel is a plain display + trigger). Regenerate/generate is
// INSTRUCTOR/ADMIN only; a `503 LLM_UNAVAILABLE` never affects the report itself (SPEC §41: the
// core works without it).
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { generateReportExplanation, getReportExplanation, problemMessageRu, queryKeys, type ProblemCode, type ReportExplanation } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

interface ExplanationPanelProps {
  sessionId: string;
  explanationAvailable: boolean;
  currentScoreChecksum: string;
  canManage: boolean;
}

export function ExplanationPanel({ sessionId, explanationAvailable, currentScoreChecksum, canManage }: ExplanationPanelProps) {
  const queryClient = useQueryClient();
  // `locallyGenerated` covers the moment right after a successful generate/regenerate: the
  // parent's `explanationAvailable` prop only flips once the report itself refetches, but the
  // POST response already has the fresh text — no reason to wait.
  const [locallyGenerated, setLocallyGenerated] = useState<ReportExplanation | null>(null);
  const [pending, setPending] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const explanationQuery = useQuery({
    queryKey: queryKeys.reports.explanation(sessionId),
    queryFn: () => getReportExplanation(sessionId),
    enabled: explanationAvailable,
    retry: false,
  });

  const explanation = locallyGenerated ?? explanationQuery.data ?? null;
  const loading = explanationAvailable && explanationQuery.isLoading;
  const stale = explanation !== null && explanation.score_report_checksum !== currentScoreChecksum;

  async function handleGenerate(regenerate: boolean): Promise<void> {
    setGenerateError(null);
    setPending(true);
    try {
      const result = await generateReportExplanation(sessionId, { regenerate, audience: 'TRAINEE' });
      setLocallyGenerated(result);
      queryClient.setQueryData(queryKeys.reports.explanation(sessionId), result);
    } catch (error) {
      if (error instanceof ProblemError && error.code === 'LLM_UNAVAILABLE') {
        setGenerateError(t('reportExplanationModelUnavailable'));
      } else {
        setGenerateError(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportExplanationTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground italic">{t('reportExplanationDisclaimer')}</p>
        {loading ? null : explanation ? (
          <>
            {stale ? (
              <p role="alert" className="text-xs text-amber-600">
                {t('reportExplanationStale')}
              </p>
            ) : null}
            <p className="text-sm whitespace-pre-wrap">{explanation.text_ru}</p>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t('reportExplanationNone')}</p>
        )}
        {explanationQuery.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {explanationQuery.error instanceof ProblemError ? problemMessageRu(explanationQuery.error.code as ProblemCode) : t('problemUnknown')}
          </p>
        ) : null}
        {generateError ? (
          <p role="alert" className="text-xs text-destructive">
            {generateError}
          </p>
        ) : null}
        {canManage ? (
          <div>
            <Button type="button" variant="outline" size="sm" disabled={pending} onClick={() => void handleGenerate(explanation !== null)}>
              {pending ? t('reportExplanationGenerating') : explanation ? t('reportExplanationRegenerateButton') : t('reportExplanationGenerateButton')}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
