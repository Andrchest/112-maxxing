// Route: /instructor/sessions/:sessionId (R4, SPEC §7, §13; D6, HLD §10.8/§10.10/§10.13). Orchestrates
// one `getInstructorSessionOverview` fetch, then refetches it on every realtime frame for this
// session (R4: "refreshes by refetching on realtime frames ... no optimistic state") — unlike the
// operator/DDS consoles' `STAGE_REFRESH_EVENT_TYPES` allowlist, this page refetches on EVERY event:
// the overview is the union of both trainee views plus the hidden layers, so there is no event type
// that cannot change something it shows (world truth revision, caller belief, a gate turn, a DDS
// leg, a resource, the call state). The connection is the instructor's own unredacted stream
// (`docs/hld/40-realtime-protocol.md` §40.1: user role INSTRUCTOR/ADMIN -> effective realtime role
// INSTRUCTOR) — no reconnect logic beyond what `WsClient` already does.
//
// R4: this page is a pure reader. It works in every session state after creation, including
// COMPLETED/ABORTED (no early return on a terminal state) — for COMPLETED it additionally links to
// the report, which is where the release control lives (`features/report/report-page.tsx`);
// nothing here duplicates that control.
import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import { getInstructorSessionOverview, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { WsClient, type ConnectionStatus } from '@/shared/realtime/ws-client';
import { SessionStagesSection } from './session-stages-section';
import { WorldTruthSection } from './world-truth-section';
import { CallerBeliefSection } from './caller-belief-section';
import { GateTurnsSection } from './gate-turns-section';
import { LiveOperatorCardSection } from './live-operator-card-section';
import { HandoffSnapshotSection } from './handoff-snapshot-section';
import { DdsWorkItemsSection } from './dds-work-items-section';
import { CallStateSection } from './call-state-section';
import { InferenceHealthSection } from './inference-health-section';
import { AbortSessionButton } from './abort-session-button';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function InstructorLiveOverviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const token = useAuthStore((state) => state.token);
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  const userRole = useAuthStore((state) => state.user?.user_role);
  const roleLabel = userRole ? t(USER_ROLE_LABEL_KEY[userRole]) : undefined;
  const canAbort = userRole === 'INSTRUCTOR' || userRole === 'ADMIN';
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const wsClientRef = useRef<WsClient | null>(null);

  const overviewQuery = useQuery({
    queryKey: queryKeys.instructor.overview(sessionId ?? ''),
    queryFn: () => getInstructorSessionOverview(sessionId ?? ''),
    enabled: sessionId !== undefined,
    retry: false,
  });

  useEffect(() => {
    const overview = overviewQuery.data;
    if (!overview || !token || wsClientRef.current) return;

    const client = new WsClient({
      sessionId: overview.session.id,
      token,
      lastSeqNo: overview.last_seq_no,
      onEvent: () => {
        void overviewQuery.refetch();
      },
      onStatusChange: setConnectionStatus,
    });
    wsClientRef.current = client;
    client.connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overviewQuery.data, token]);

  useEffect(() => {
    return () => {
      wsClientRef.current?.disconnect();
      wsClientRef.current = null;
    };
  }, []);

  if (!sessionId) {
    return null;
  }

  if (overviewQuery.isLoading) {
    return (
      <AppShell title={t('instructorLiveOverviewTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('instructorOverviewLoading')}</p>
      </AppShell>
    );
  }

  if (overviewQuery.isError) {
    const error = overviewQuery.error;
    const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell title={t('instructorLiveOverviewTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const overview = overviewQuery.data;
  if (!overview) {
    return null;
  }

  const isTerminal = overview.session.state === 'COMPLETED' || overview.session.state === 'ABORTED';

  return (
    <AppShell
      title={t('instructorLiveOverviewTitle')}
      role={roleLabel}
      userLabel={userLabel}
      connectionStatus={connectionStatus}
      readiness={overview.inference_health.overall}
    >
      <div className="flex items-center justify-between gap-2">
        <h1 className="font-heading text-lg font-medium">{t('instructorLiveOverviewTitle')}</h1>
        <div className="flex items-center gap-2">
          {!isTerminal && canAbort ? (
            <AbortSessionButton sessionId={sessionId} onAborted={() => void overviewQuery.refetch()} />
          ) : null}
          {isTerminal ? (
            <Button asChild size="sm">
              <Link to={`/report/${sessionId}`}>{t('reportViewReportButton')}</Link>
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SessionStagesSection session={overview.session} stages={overview.stages} />
        <CallStateSection callState={overview.call_state} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <WorldTruthSection worldTruth={overview.world_truth} />
        <CallerBeliefSection callerBelief={overview.caller_belief} />
      </div>
      <div className="mt-4">
        <GateTurnsSection gateTurns={overview.gate_turns} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <LiveOperatorCardSection card={overview.card} />
        <HandoffSnapshotSection handoff={overview.handoff} card={overview.card} />
      </div>
      <div className="mt-4">
        <DdsWorkItemsSection assignments={overview.assignments} resources={overview.resources} />
      </div>
      <div className="mt-4">
        <InferenceHealthSection health={overview.inference_health} />
      </div>
    </AppShell>
  );
}
