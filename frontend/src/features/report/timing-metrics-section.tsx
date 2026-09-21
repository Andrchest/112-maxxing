// §29 item 13: timing metrics (SPEC §27, §46 item 16). The aggregate (`timing_metrics`, shared
// with `InferenceMetricsPage` per the recon — one aggregator on the backend, one rendering here)
// plus the raw per-call rows from `listInferenceMetrics`, so a trainee/instructor can see the
// actual measurements behind the aggregate, not just the summary numbers. A `null` metric renders
// the `reportTimingMetricsNoData` string (ru.ts) — never 0 (SPEC §27: never fake a benchmark value).
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { listInferenceMetrics, problemMessageRu, queryKeys, type ProblemCode, type TimingMetricsView } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

function metricText(value: number | null): string {
  return value === null ? t('reportTimingMetricsNoData') : String(value);
}

interface StatRowProps {
  label: string;
  value: number | null;
}

function StatRow({ label, value }: StatRowProps) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums">{metricText(value)}</span>
    </div>
  );
}

interface TimingMetricsSectionProps {
  sessionId: string;
  timingMetrics: TimingMetricsView;
}

export function TimingMetricsSection({ sessionId, timingMetrics }: TimingMetricsSectionProps) {
  const metricsQuery = useQuery({
    queryKey: queryKeys.reports.inferenceMetrics(sessionId),
    queryFn: () => listInferenceMetrics(sessionId),
  });

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportTimingMetricsTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <StatRow label={t('reportTimingMetricsTurnCountLabel')} value={timingMetrics.turn_count} />
          <StatRow label={t('reportTimingMetricsSpeechToAudioP50Label')} value={timingMetrics.speech_end_to_first_audio_ms_p50} />
          <StatRow label={t('reportTimingMetricsSpeechToAudioP95Label')} value={timingMetrics.speech_end_to_first_audio_ms_p95} />
          <StatRow label={t('reportTimingMetricsAsrP50Label')} value={timingMetrics.asr_latency_ms_p50} />
          <StatRow label={t('reportTimingMetricsLlmTtftP50Label')} value={timingMetrics.llm_ttft_ms_p50} />
          <StatRow label={t('reportTimingMetricsTtsFirstAudioP50Label')} value={timingMetrics.tts_first_audio_ms_p50} />
          <StatRow label={t('reportTimingMetricsBargeInP95Label')} value={timingMetrics.barge_in_cutoff_ms_p95} />
          <StatRow label={t('reportTimingMetricsFallbackCountLabel')} value={timingMetrics.fallback_count} />
        </div>

        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('reportTimingMetricsRawTitle')}</h3>
          {metricsQuery.isError ? (
            <p role="alert" className="text-xs text-destructive">
              {metricsQuery.error instanceof ProblemError ? problemMessageRu(metricsQuery.error.code as ProblemCode) : t('problemUnknown')}
            </p>
          ) : null}
          {!metricsQuery.data || metricsQuery.data.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('reportTimingMetricsNoData')}</p>
          ) : (
            <ul className="flex max-h-64 flex-col gap-1 overflow-auto">
              {metricsQuery.data.items.map((metric) => (
                <li key={metric.id} className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono">{metric.component}</span>
                  <span className="text-muted-foreground">
                    {metric.provider}/{metric.model}
                  </span>
                  <span className="font-mono tabular-nums">
                    {t('reportTimingMetricsRawTtftLabel')}: {metricText(metric.ttft_ms)}
                  </span>
                  <span className="font-mono tabular-nums">
                    {t('reportTimingMetricsRawTotalLabel')}: {metricText(metric.total_latency_ms)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
