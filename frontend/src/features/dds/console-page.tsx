// Route: /dds/:sessionId (SPEC §10, §11, §32, §39; D3, D12). The DDS analogue of
// `features/operator/console-page.tsx`: refresh-restore (GET snapshot -> hydrate stores -> open
// the WebSocket and resume from `last_seq_no`), then live WS event folds between refreshes. The
// DDS console can never show operator-card-live data, transcript or world truth (D3) — this page
// never fetches or stores any of that, and `no-world-truth-guard.test.ts` asserts the generated
// types it consumes carry none of it either.
import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore, useSessionEventsStore } from '@/entities/session';
import { useWorkItemStore, applyWorkItemEvent } from '@/entities/work-item';
import { useResourceStore, applyResourceEvent } from '@/entities/resource';
import { useNotificationStore, applyNotificationEvent } from '@/entities/notification';
import { useRadioStore, applyRadioMessageEvent } from '@/entities/radio';
import { getSessionSnapshot, listDdsResources, problemMessageRu, queryKeys, type ProblemCode, type UserRole } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { WsClient, type ConnectionStatus } from '@/shared/realtime/ws-client';
import { WorkItemPanel } from './work-item-panel';
import { StageActionBar } from './stage-action-bar';
import { CloseDialog } from './close-dialog';
import { ResourceBoard } from './resource-board';
import { DispatchTray } from './dispatch-tray';
import { NotificationsPanel } from './notifications-panel';
import { RadioLog } from './radio-log';
import { StatusUpdateForm } from './status-update-form';
import { LegsPanel } from './legs-panel';
import { CardIssueButton } from './card-issue-button';
import { DdsHeaderStrip } from './dds-header-strip';
import { DdsSideDrawer } from './dds-side-drawer';
import { DdsPhoneWidget } from './phone-widget';
import { DDS_CALL_EVENT_TYPES, useDdsCallStore } from '@/entities/call';
import { PROPOSAL_EVENT_TYPE, useCallProposalStore } from './call-proposals';
import { ddsStageStateLabelRu } from './dds-labels';
import { WaitingForCardNotice } from './waiting-for-card-notice';
import { WAITING_POLL_INTERVAL_MS } from './waiting-reason';

// I3 E5c: events that mean "the legs list (or a leg's history) may have changed elsewhere" —
// broadcast, so another ДДС participant's command must reach this caller's read too
// (REQ-5294/5295). Re-fetched through react-query invalidation, the same "server's response, not
// a local fold" doctrine `STAGE_REFRESH_EVENT_TYPES` already applies to the stage snapshot.
const LEGS_REFRESH_EVENT_TYPES = new Set([
  'DDS_CARD_OPENED',
  'DDS_SERVICE_STATUS_SET',
  'DDS_CARD_ISSUE_FLAGGED',
  'DDS_CARD_STATUS_CHANGED',
]);

/** Event types this page re-fetches the snapshot for, rather than folding (D12 design decision
 * #1: "no optimistic stage changes" — a re-fetch is still "the server's response"). Mirrors
 * `features/operator/console-page.tsx`'s `STAGE_REFRESH_EVENT_TYPES`. `RESOURCE_STATUS_CHANGED`
 * is included (D14): a resource's status can change from the simulated world clock alone, with no
 * DDS command in between, so `available_actions` (e.g. `select_resource`/`dispatch_additional`)
 * must be re-pulled from the server on that event too, not only on a stage-state change. */
const STAGE_REFRESH_EVENT_TYPES = new Set([
  'STAGE_STATE_CHANGED',
  'HANDOFF_RECEIVED',
  'ROLE_TRANSITION_STARTED',
  'ROLE_TRANSITION_COMPLETED',
  'RESOURCE_STATUS_CHANGED',
]);

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function DdsConsolePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const queryClient = useQueryClient();
  const token = useAuthStore((state) => state.token);
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  // D4: the header role chip is the signed-in account's role, not the simulation role.
  const userRole = useAuthStore((state) => state.user?.user_role);
  const roleLabel = userRole ? t(USER_ROLE_LABEL_KEY[userRole]) : undefined;
  const workItem = useWorkItemStore((state) => state.workItem);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const wsClientRef = useRef<WsClient | null>(null);

  const snapshotQuery = useQuery({
    queryKey: queryKeys.sessions.snapshot(sessionId ?? ''),
    queryFn: () => getSessionSnapshot(sessionId ?? ''),
    enabled: sessionId !== undefined,
    // I6 UX: while there is no work item yet (the lesson not started, the card's arrival offset
    // not reached, the 112 stage not handed off), re-read the snapshot so the card appears by
    // itself. I6 FIX1: `WsClient` now delivers the events after a hole in this viewer's filtered
    // stream (it used to drop them), so HANDOFF_RECEIVED reaches the page live; this poll stays
    // for the not-yet-started case — a `READY` session whose card has not been issued yet, where
    // the page must not depend on the socket (or its first event) to notice the start.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || data.work_item !== null) return false;
      return data.session.state === 'COMPLETED' || data.session.state === 'ABORTED' ? false : WAITING_POLL_INTERVAL_MS;
    },
  });

  // I3 E5c: the resource board/dispatch tray (and the board data behind them) are kept entirely
  // behind `dds_mode: RESOURCE_PICKER` — a memo session never fetches the resource board.
  const resourcesQuery = useQuery({
    queryKey: queryKeys.dds.resources(sessionId ?? ''),
    queryFn: () => listDdsResources(sessionId ?? ''),
    enabled:
      sessionId !== undefined &&
      snapshotQuery.data?.work_item != null &&
      snapshotQuery.data.session.variants.dds_mode !== 'MEMO_STATUSES',
  });

  useEffect(() => {
    const snapshot = snapshotQuery.data;
    if (!snapshot) return;
    useWorkItemStore.getState().setFromSnapshot(snapshot);
  }, [snapshotQuery.data]);

  useEffect(() => {
    if (resourcesQuery.data) {
      useResourceStore.getState().setResources(resourcesQuery.data.items);
    }
  }, [resourcesQuery.data]);

  useEffect(() => {
    const snapshot = snapshotQuery.data;
    if (!snapshot || !token || wsClientRef.current) return;

    useSessionEventsStore.getState().reset(snapshot.session.id, snapshot.last_seq_no);

    const client = new WsClient({
      sessionId: snapshot.session.id,
      token,
      lastSeqNo: snapshot.last_seq_no,
      onEvent: (event) => {
        useSessionEventsStore.getState().applyEvent(event);
        useWorkItemStore.setState((state) => ({ workItem: applyWorkItemEvent(state.workItem, event) }));
        useResourceStore.setState((state) => ({ resources: applyResourceEvent(state.resources, event) }));
        const incidentId = snapshot.session.incident_id;
        useNotificationStore.setState((state) => ({ items: applyNotificationEvent(state.items, event, { incidentId }) }));
        useRadioStore.setState((state) => ({ messages: applyRadioMessageEvent(state.messages, event, { incidentId }) }));
        if (STAGE_REFRESH_EVENT_TYPES.has(event.event_type)) {
          void snapshotQuery.refetch();
        }
        if (LEGS_REFRESH_EVENT_TYPES.has(event.event_type)) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.dds.legs(snapshot.session.id) });
        }
        // I3 E6b: the ДДС phone line — fold the event at once, then re-read the server's view.
        if (DDS_CALL_EVENT_TYPES.has(event.event_type)) {
          useDdsCallStore.getState().applyEvent(event);
          void queryClient.invalidateQueries({ queryKey: queryKeys.dds.calls(snapshot.session.id) });
          // I3 E6c: a leg's `live_call_id` follows its service-head call.
          void queryClient.invalidateQueries({ queryKey: queryKeys.dds.legs(snapshot.session.id) });
        }
        // I3 E6c: a status the service head reported — offered on the leg's pencil form.
        if (event.event_type === PROPOSAL_EVENT_TYPE) {
          useCallProposalStore.getState().applyEvent(event);
        }
      },
      onStatusChange: setConnectionStatus,
    });
    wsClientRef.current = client;
    client.connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotQuery.data, token]);

  useEffect(() => {
    return () => {
      wsClientRef.current?.disconnect();
      wsClientRef.current = null;
    };
  }, []);

  if (!sessionId) {
    return null;
  }

  if (snapshotQuery.isLoading) {
    return (
      <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme>
        <p className="text-sm text-muted-foreground">{t('ddsConsoleLoading')}</p>
      </AppShell>
    );
  }

  if (snapshotQuery.isError) {
    const error = snapshotQuery.error;
    const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const snapshot = snapshotQuery.data;

  // E16: the link from the "session completed" state to the report (recon §6/§7) — a
  // COMPLETED/ABORTED session has nothing left to command here, only the report to view.
  if (snapshot && (snapshot.session.state === 'COMPLETED' || snapshot.session.state === 'ABORTED')) {
    return (
      <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme>
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 pt-12 text-center">
          <p className="text-sm text-muted-foreground">{t('reportSessionCompletedNotice')}</p>
          <Button asChild size="sm">
            <Link to={`/report/${sessionId}`}>{t('reportViewReportButton')}</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  if (!snapshot || snapshot.work_item === null) {
    return (
      <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme>
        {snapshot ? <WaitingForCardNotice snapshot={snapshot} snapshotFetchedAtMs={snapshotQuery.dataUpdatedAt} /> : null}
      </AppShell>
    );
  }

  // I3 E5c (70 §70.4, D16): the memo's per-service blocks replace the resource board/dispatch
  // tray under `dds_mode: MEMO_STATUSES`; `RESOURCE_PICKER` keeps today's UI exactly (the brief's
  // "kept behind dds_mode = RESOURCE_PICKER"). `dds_mode` is immutable per session (D16), so
  // reading it off the snapshot's own `SessionVariants` needs no store of its own.
  const isMemoMode = snapshot.session.variants.dds_mode === 'MEMO_STATUSES';
  // I3 E6b (80 §80.5, D25): `dds_brigade_call: ON` — the ДДС workstation has a phone (memo mode
  // only, R41). Under `OFF` the widget does not exist at all.
  const hasPhone = snapshot.session.variants.dds_brigade_call === 'ON';

  // I3 E5c (manager review): the memo layout follows the reference's shape (header strip on top,
  // a two-column card summary, the services tab bar spanning the bottom, product-only panels in a
  // closed-by-default drawer) — `RESOURCE_PICKER` keeps today's three-column console unchanged.
  if (isMemoMode) {
    // I3 E7a (manager review): a full-height layout — `AppShell`'s `fillHeight` stops `main`
    // itself from scrolling, so the tab bar (`LegsPanel`, pinned as the last, non-scrolling flex
    // child below) always sits at the true viewport bottom, including when the card summary
    // above it is shorter than the viewport (a `position: sticky` bar alone only pins once there
    // is something to scroll, which is the bug the manager's review reported). Everything above
    // the bar lives in its own `overflow-y-auto` region instead.
    return (
      <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme fillHeight>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
          {workItem ? (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <Badge variant="outline" data-slot="dds-stage-badge">
                {t('ddsStageLabel')}: {ddsStageStateLabelRu(workItem.state)}
              </Badge>
              <div className="flex flex-wrap gap-2" data-tour="dds-actions">
                <StageActionBar sessionId={sessionId} />
                <CloseDialog sessionId={sessionId} />
                <CardIssueButton sessionId={sessionId} />
                <DdsSideDrawer sessionId={sessionId} />
              </div>
            </div>
          ) : null}
          {hasPhone ? (
            <div className="mb-3">
              <DdsPhoneWidget sessionId={sessionId} />
            </div>
          ) : null}
          <div className="flex flex-col gap-4">
            {workItem ? <DdsHeaderStrip sessionId={sessionId} workItem={workItem} /> : null}
            <WorkItemPanel />
          </div>
        </div>
        <LegsPanel sessionId={sessionId} />
      </AppShell>
    );
  }

  return (
    <AppShell backTo="/sessions" title={t('ddsTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus} referenceTheme>
      {workItem ? (
        <div className="mb-3">
          <Badge variant="outline" data-slot="dds-stage-badge">
            {t('ddsStageLabel')}: {ddsStageStateLabelRu(workItem.state)}
          </Badge>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr_340px]">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2" data-tour="dds-actions">
            <StageActionBar sessionId={sessionId} />
            <CloseDialog sessionId={sessionId} />
            <CardIssueButton sessionId={sessionId} />
          </div>
          {/* I4 E21: no tab bar in the picker console, so the recipients stay on the card. */}
          <WorkItemPanel showRecipients />
        </div>
        <div className="flex flex-col gap-4" data-tour="dds-services">
          <ResourceBoard sessionId={sessionId} />
          <DispatchTray sessionId={sessionId} />
        </div>
        <div className="flex flex-col gap-4">
          <NotificationsPanel sessionId={sessionId} />
          <RadioLog sessionId={sessionId} />
          <StatusUpdateForm sessionId={sessionId} />
        </div>
      </div>
    </AppShell>
  );
}
