// Route: /dds/:sessionId (SPEC §10, §11, §32, §39; D3, D12). The DDS analogue of
// `features/operator/console-page.tsx`: refresh-restore (GET snapshot -> hydrate stores -> open
// the WebSocket and resume from `last_seq_no`), then live WS event folds between refreshes. The
// DDS console can never show operator-card-live data, transcript or world truth (D3) — this page
// never fetches or stores any of that, and `no-world-truth-guard.test.ts` asserts the generated
// types it consumes carry none of it either.
import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { useAuthStore, useSessionEventsStore } from '@/entities/session';
import { useWorkItemStore, applyWorkItemEvent } from '@/entities/work-item';
import { useResourceStore, applyResourceEvent } from '@/entities/resource';
import { useNotificationStore, applyNotificationEvent } from '@/entities/notification';
import { useRadioStore, applyRadioMessageEvent } from '@/entities/radio';
import { getSessionSnapshot, listDdsResources, problemMessageRu, queryKeys, type ProblemCode } from '@/shared/api';
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
import { ddsStageStateLabelRu } from './dds-labels';

/** Event types this page re-fetches the snapshot for, rather than folding (D12 design decision
 * #1: "no optimistic stage changes" — a re-fetch is still "the server's response"). Mirrors
 * `features/operator/console-page.tsx`'s `STAGE_REFRESH_EVENT_TYPES`. */
const STAGE_REFRESH_EVENT_TYPES = new Set(['STAGE_STATE_CHANGED', 'HANDOFF_RECEIVED', 'ROLE_TRANSITION_STARTED', 'ROLE_TRANSITION_COMPLETED']);

export function DdsConsolePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const token = useAuthStore((state) => state.token);
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  const workItem = useWorkItemStore((state) => state.workItem);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const wsClientRef = useRef<WsClient | null>(null);

  const snapshotQuery = useQuery({
    queryKey: queryKeys.sessions.snapshot(sessionId ?? ''),
    queryFn: () => getSessionSnapshot(sessionId ?? ''),
    enabled: sessionId !== undefined,
  });

  const resourcesQuery = useQuery({
    queryKey: queryKeys.dds.resources(sessionId ?? ''),
    queryFn: () => listDdsResources(sessionId ?? ''),
    enabled: sessionId !== undefined && snapshotQuery.data?.work_item != null,
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
      <AppShell title={t('ddsTitle')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('ddsConsoleLoading')}</p>
      </AppShell>
    );
  }

  if (snapshotQuery.isError) {
    const error = snapshotQuery.error;
    const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell title={t('ddsTitle')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const snapshot = snapshotQuery.data;
  if (!snapshot || snapshot.work_item === null) {
    return (
      <AppShell title={t('ddsTitle')} role={t('roleTypeDds')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('ddsConsoleNoWorkItem')}</p>
      </AppShell>
    );
  }

  return (
    <AppShell title={t('ddsTitle')} role={t('roleTypeDds')} userLabel={userLabel} connectionStatus={connectionStatus}>
      {workItem ? (
        <div className="mb-3">
          <Badge variant="outline" data-slot="dds-stage-badge">
            {t('ddsStageLabel')}: {ddsStageStateLabelRu(workItem.state)}
          </Badge>
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr_340px]">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <StageActionBar sessionId={sessionId} />
            <CloseDialog sessionId={sessionId} />
          </div>
          <WorkItemPanel />
        </div>
        <div className="flex flex-col gap-4">
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
