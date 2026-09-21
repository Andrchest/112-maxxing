// Route: /operator/:sessionId (SPEC §9, §10, §32, §39; D3, D12). Orchestrates the refresh-restore
// sequence (SPEC §39, §42 test 13; `docs/hld/40-realtime-protocol.md` §40.5): GET snapshot ->
// hydrate the stage/card/call-state stores -> open the WebSocket and resume from
// `snapshot.last_seq_no`. Every store write here comes from a server response or a server event
// payload (D12 design decision #1) — this page decides nothing about the simulation itself.
import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { useAuthStore, useSessionEventsStore, useCallStateStore } from '@/entities/session';
import { useCardStore, applyCardEvent } from '@/entities/card';
import { applyCallEvent } from '@/entities/call';
import { useStageStore } from '@/entities/stage';
import { getSessionSnapshot, problemMessageRu, queryKeys, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { WsClient, type ConnectionStatus } from '@/shared/realtime/ws-client';
import { PhoneWidget } from './phone-widget';
import { StageActionBar } from './stage-action-bar';
import { CardForm } from './card-form';
import { ServicesPanel } from './services-panel';
import { TranscriptPanel } from './transcript-panel';
import { HandoffPreparationView } from './handoff-preparation-view';
import { NotificationsPlaceholder } from './notifications-placeholder';

/** Event types that can change `available_actions` or the stage/call state for this role. On any
 * of these the page re-fetches the snapshot rather than guessing the new state locally (D12
 * design decision #1: "no optimistic stage changes"; a re-fetch is still "the server's
 * response", just triggered reactively instead of by a click). */
const STAGE_REFRESH_EVENT_TYPES = new Set(['STAGE_STATE_CHANGED', 'CALL_RINGING', 'CALL_ANSWERED', 'CALL_ENDED', 'HANDOFF_CREATED']);

export function OperatorConsolePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const token = useAuthStore((state) => state.token);
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  const stageState = useStageStore((state) => state.stageState);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('idle');
  const wsClientRef = useRef<WsClient | null>(null);

  const snapshotQuery = useQuery({
    queryKey: queryKeys.sessions.snapshot(sessionId ?? ''),
    queryFn: () => getSessionSnapshot(sessionId ?? ''),
    enabled: sessionId !== undefined,
  });

  // Hydrate the stage/card/call-state stores from every snapshot fetch — the initial refresh
  // restore and every reactive re-fetch triggered below (SPEC §39, D12 design decision #1).
  useEffect(() => {
    const snapshot = snapshotQuery.data;
    if (!snapshot) return;
    useStageStore.getState().setFromSnapshot(snapshot);
    useCardStore.getState().setCard(snapshot.card);
    useCallStateStore.getState().setCallState(snapshot.call_state);
  }, [snapshotQuery.data]);

  // Open the WebSocket exactly once per mount, resuming from the snapshot's last_seq_no (HLD
  // §40.5 step 3). Guarded by the ref so a reactive re-fetch (below) never reconnects.
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
        // Idempotent folds onto server-shaped data only (D12 design decision #5) — never a
        // client-derived value. ASR_FINAL and every other event type these reducers do not
        // recognise pass through unchanged (DESIGN 2: the card is never auto-filled from ASR).
        // CARD_FIELD_CHANGED from this log and a setCardField command response both call
        // `useCardStore.getState().setCard(...)`-equivalent updates, so the two converge on the
        // same value regardless of which arrives first (D12 design decision #5).
        useCardStore.setState((state) => ({ card: applyCardEvent(state.card, event) }));
        useCallStateStore.setState((state) => ({ callState: applyCallEvent(state.callState, event) }));
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
      <AppShell title={t('operatorTitle')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('operatorConsoleLoading')}</p>
      </AppShell>
    );
  }

  if (snapshotQuery.isError) {
    const error = snapshotQuery.error;
    const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell title={t('operatorTitle')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const snapshot = snapshotQuery.data;
  if (!snapshot || snapshot.card === null) {
    return (
      <AppShell title={t('operatorTitle')} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('operatorConsoleWrongRole')}</p>
      </AppShell>
    );
  }

  return (
    <AppShell
      title={t('operatorTitle')}
      role={t('roleTypeOperator112')}
      userLabel={userLabel}
      connectionStatus={connectionStatus}
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr_320px]">
        <div className="flex flex-col gap-4">
          <PhoneWidget sessionId={sessionId} />
          <StageActionBar sessionId={sessionId} />
        </div>
        <div>
          {stageState === 'HANDOFF_PREPARATION' ? (
            <HandoffPreparationView sessionId={sessionId} />
          ) : (
            <CardForm sessionId={sessionId} />
          )}
        </div>
        <div className="flex flex-col gap-4">
          <ServicesPanel sessionId={sessionId} />
          <TranscriptPanel />
          <NotificationsPlaceholder />
        </div>
      </div>
    </AppShell>
  );
}
