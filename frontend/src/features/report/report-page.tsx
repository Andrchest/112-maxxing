// Route: /report/:sessionId (SPEC §29 "Build a real report UI", D12, R11). Orchestrates one
// `getSessionReport` fetch (TanStack Query, no realtime concern — a finished session's report is
// a plain REST read, per the recon) and renders one component per §29 item. Every section the
// viewer may not see comes back empty/null from the API and is hidden, never shown as an error
// (R3) — this page never filters anything itself (see `no-score-math-guard.test.ts` for the
// numeric half of that guarantee).
import { useState } from 'react';
import { useParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { getSessionReport, releaseReportToTrainee, problemMessageRu, queryKeys, type ProblemCode, type ReportReleaseView, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { TotalsSection } from './totals-section';
import { CategoriesSection } from './categories-section';
import { CriticalErrorsSection } from './critical-errors-section';
import { TimelineSection } from './timeline-section';
import { timelineEntryRowId } from './timeline-row-id';
import { TranscriptAudioPanel } from './transcript-audio-panel';
import { FinalCardSection } from './final-card-section';
import { TruthDiffSection } from './truth-diff-section';
import { HandoffSection } from './handoff-section';
import { DdsDecisionsSection } from './dds-decisions-section';
import { ResourceTimelineSection } from './resource-timeline-section';
import { TimingMetricsSection } from './timing-metrics-section';
import { RuleEvidenceSection } from './rule-evidence-section';
import { ExplanationPanel } from './explanation-panel';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function ReportPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const user = useAuthStore((state) => state.user);
  const userLabel = user?.display_name_ru;
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;
  const canManage = user?.user_role === 'INSTRUCTOR' || user?.user_role === 'ADMIN';
  const queryClient = useQueryClient();

  const [highlightedSeqNo, setHighlightedSeqNo] = useState<number | null>(null);
  const [releaseInfo, setReleaseInfo] = useState<ReportReleaseView | null>(null);
  const [releasePending, setReleasePending] = useState(false);
  const [releaseError, setReleaseError] = useState<string | null>(null);

  const reportQuery = useQuery({
    queryKey: queryKeys.reports.detail(sessionId ?? ''),
    queryFn: () => getSessionReport(sessionId ?? ''),
    enabled: sessionId !== undefined,
    // These 403/409 states are deterministic business rules (release gate, session not
    // COMPLETED), not transient failures — retrying would only delay showing the right message.
    retry: false,
  });

  async function handleRelease(): Promise<void> {
    if (!sessionId) return;
    setReleaseError(null);
    setReleasePending(true);
    try {
      const result = await releaseReportToTrainee(sessionId);
      setReleaseInfo(result);
      await queryClient.invalidateQueries({ queryKey: queryKeys.reports.detail(sessionId) });
    } catch (error) {
      setReleaseError(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setReleasePending(false);
    }
  }

  function handleJumpToEvent(seqNo: number): void {
    setHighlightedSeqNo(seqNo);
    document.getElementById(timelineEntryRowId(seqNo))?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  }

  if (!sessionId) {
    return null;
  }

  if (reportQuery.isLoading) {
    return (
      <AppShell title={t('reportTitle')} role={roleLabel} userLabel={userLabel}>
        <h1 className="sr-only">{t('reportTitle')}</h1>
        <p className="text-sm text-muted-foreground">{t('reportLoading')}</p>
      </AppShell>
    );
  }

  if (reportQuery.isError) {
    const error = reportQuery.error;
    const code = error instanceof ProblemError ? error.code : null;
    const stateMessage =
      code === 'REPORT_NOT_RELEASED'
        ? t('reportNotReleasedTitle')
        : code === 'REPORT_NOT_READY'
          ? t('reportNotReadyTitle')
          : code === 'NOT_FOUND'
            ? t('notFoundTitle')
            : error instanceof ProblemError
              ? problemMessageRu(error.code as ProblemCode)
              : t('problemUnknown');
    return (
      <AppShell title={t('reportTitle')} role={roleLabel} userLabel={userLabel}>
        <h1 className="sr-only">{t('reportTitle')}</h1>
        <p role={code === 'REPORT_NOT_RELEASED' || code === 'REPORT_NOT_READY' ? undefined : 'alert'} className="text-sm text-muted-foreground">
          {stateMessage}
        </p>
      </AppShell>
    );
  }

  const report = reportQuery.data;
  if (!report) {
    return null;
  }

  return (
    <AppShell title={t('reportTitle')} role={roleLabel} userLabel={userLabel}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-heading text-lg font-medium">{t('reportTitle')}</h1>
        {canManage ? (
          <div className="flex items-center gap-2">
            <Badge variant={report.released ? 'default' : 'outline'}>{report.released ? t('reportReleasedBadge') : t('reportNotReleasedBadge')}</Badge>
            <Button type="button" size="sm" disabled={releasePending} onClick={() => void handleRelease()}>
              {t('reportReleaseButton')}
            </Button>
          </div>
        ) : null}
      </div>
      {releaseInfo?.released_at ? (
        <p className="text-xs text-muted-foreground">
          {t('reportReleasedAtLabel')}: {formatTimestampRu(releaseInfo.released_at)}
        </p>
      ) : null}
      {releaseError ? (
        <p role="alert" className="text-xs text-destructive">
          {releaseError}
        </p>
      ) : null}

      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TotalsSection scoreReport={report.score_report} />
        <CategoriesSection byCategory={report.score_report.by_category} />
      </div>
      <div className="mt-4">
        <CriticalErrorsSection criticalErrors={report.score_report.critical_errors} />
      </div>
      <div className="mt-4">
        <TimelineSection timeline={report.timeline} highlightedSeqNo={highlightedSeqNo} />
      </div>
      <div className="mt-4">
        <TranscriptAudioPanel sessionId={sessionId} transcript={report.transcript} audioSegments={report.audio_segments} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <FinalCardSection card={report.final_card} />
        <HandoffSection handoff={report.handoff} fieldSpecs={report.final_card.field_specs} />
      </div>
      <div className="mt-4">
        <TruthDiffSection entries={report.truth_vs_card_diff} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DdsDecisionsSection decisions={report.dds_decisions} />
        <ResourceTimelineSection entries={report.resource_timeline} />
      </div>
      <div className="mt-4">
        <TimingMetricsSection sessionId={sessionId} timingMetrics={report.timing_metrics} />
      </div>
      <div className="mt-4">
        <RuleEvidenceSection results={report.score_report.results} onJumpToEvent={handleJumpToEvent} />
      </div>
      <div className="mt-4">
        <ExplanationPanel
          sessionId={sessionId}
          explanationAvailable={report.explanation_available}
          currentScoreChecksum={report.score_report.checksum}
          canManage={canManage}
        />
      </div>
    </AppShell>
  );
}
