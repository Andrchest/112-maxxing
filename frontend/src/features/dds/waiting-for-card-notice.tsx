// I6 UX (owner: the old `ddsConsoleNoWorkItem` dead end left the trainee not knowing what to do):
// the ДДС console's empty state. A lesson creates its card sessions `READY` at once
// (70 §70.3.2), so «Мои занятия» offers «Открыть» before the instructor has started anything; this
// notice says WHY there is no request yet and WHAT happens next, from the snapshot the page already
// has plus the trainee's own lesson (`GET /lessons/{id}` admits a lesson participant). The console
// polls its snapshot while this notice is shown, so the card appears without a reload.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { t } from '@/shared/i18n';
import { getLesson, queryKeys, type SessionSnapshot } from '@/shared/api';
import { WAITING_POLL_INTERVAL_MS, waitingReason, type WaitingReason } from './waiting-reason';

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function reasonText(reason: WaitingReason): string {
  switch (reason.kind) {
    case 'LESSON_NOT_STARTED':
      return t('ddsWaitingLessonNotStarted');
    case 'SESSION_NOT_STARTED':
      return t('ddsWaitingSessionNotStarted');
    case 'CARD_IN':
      return `${t('ddsWaitingCardInPrefix')} ${formatCountdown(reason.seconds)}.`;
    case 'CARD_DUE':
      return t('ddsWaitingCardDue');
    case 'AFTER_PREVIOUS_112_STAGE':
      return t('ddsWaitingAfterPrevious112Stage');
    case 'AFTER_PREVIOUS_SESSION':
      return t('ddsWaitingAfterPreviousSession');
    case 'AWAITING_HANDOFF':
      return t('ddsWaitingAwaitingHandoff');
  }
}

interface WaitingForCardNoticeProps {
  snapshot: SessionSnapshot;
  /** `snapshotQuery.dataUpdatedAt` — with `snapshot.server_time_utc`, the client→server clock skew. */
  snapshotFetchedAtMs: number;
}

export function WaitingForCardNotice({ snapshot, snapshotFetchedAtMs }: WaitingForCardNoticeProps) {
  const lessonId = snapshot.session.lesson_id;
  const lessonQuery = useQuery({
    queryKey: queryKeys.lessons.detail(lessonId ?? ''),
    queryFn: () => getLesson(lessonId ?? ''),
    enabled: lessonId !== null,
    retry: false,
    refetchInterval: WAITING_POLL_INTERVAL_MS,
  });
  const [clientNowMs, setClientNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setClientNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const serverSkewMs = snapshotFetchedAtMs > 0 ? Date.parse(snapshot.server_time_utc) - snapshotFetchedAtMs : 0;
  const reason = waitingReason(snapshot, lessonQuery.data, clientNowMs + (Number.isFinite(serverSkewMs) ? serverSkewMs : 0));

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-2 pt-12 text-center" data-slot="dds-waiting-notice" data-reason={reason.kind}>
      <h2 className="text-base font-semibold">{t('ddsWaitingTitle')}</h2>
      <p className="text-sm">{reasonText(reason)}</p>
      <p className="text-xs text-muted-foreground">{t('ddsWaitingAutoRefresh')}</p>
    </div>
  );
}
