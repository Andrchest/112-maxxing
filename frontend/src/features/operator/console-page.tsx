// Route: /operator/:sessionId (SPEC §9, §10, §32, §39; D3, D12). Orchestrates the refresh-restore
// sequence (SPEC §39, §42 test 13; `docs/hld/40-realtime-protocol.md` §40.5): GET snapshot ->
// hydrate the stage/card/call-state stores -> open the WebSocket and resume from
// `snapshot.last_seq_no`. Every store write here comes from a server response or a server event
// payload (D12 design decision #1) — this page decides nothing about the simulation itself.
//
// E10: once `complete_stage` fires, the session may enter `ROLE_TRANSITION` (SPEC §10.10) — this
// page then swaps the normal card layout for a countdown screen. The countdown is ticked locally
// between snapshot refreshes (DESIGN: "no client clock authority beyond ticking a countdown
// between events") from `session.transition_continue_available_at_offset_ms` minus
// `session.monotonic_offset_ms`, both server-sent; `continueToNextStage` is refused with
// `409 INVALID_TRANSITION` before that offset and before the next stage has an assigned
// participant, so an early click is harmless. After it succeeds this page re-fetches the snapshot
// and routes a `FULL_CYCLE_SINGLE_TRAINEE` trainee whose next stage is `DDS` to `/dds/:sessionId`.
import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore, useSessionEventsStore, useCallStateStore } from '@/entities/session';
import { useCardStore, applyCardEvent } from '@/entities/card';
import { applyCallEvent } from '@/entities/call';
import { useStageStore } from '@/entities/stage';
import { useNotificationStore, applyNotificationEvent } from '@/entities/notification';
import { getSessionSnapshot, continueToNextStage, problemMessageRu, queryKeys, type ProblemCode, type SessionDetail, type UserRole } from '@/shared/api';
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
const STAGE_REFRESH_EVENT_TYPES = new Set([
  'STAGE_STATE_CHANGED',
  'CALL_RINGING',
  'CALL_ANSWERED',
  'CALL_ENDED',
  'HANDOFF_CREATED',
  'ROLE_TRANSITION_STARTED',
  'ROLE_TRANSITION_COMPLETED',
]);

function computeRemainingSeconds(targetOffsetMs: number | null, nowOffsetMs: number): number {
  return targetOffsetMs === null ? 0 : Math.max(0, Math.ceil((targetOffsetMs - nowOffsetMs) / 1000));
}

/** Ticks a countdown, in whole seconds, from `targetOffsetMs - nowOffsetMs` down to 0, purely
 * locally between server refreshes (DESIGN: no client clock authority beyond this). Resetting the
 * baseline when a fresh `targetOffsetMs`/`nowOffsetMs` pair arrives happens during render itself
 * (React docs: "adjusting state when a prop changes"), the same idiom `card-form.tsx`'s
 * `CardFieldRow` already uses — not a synchronous `setState` inside the effect body. */
function useCountdownSeconds(targetOffsetMs: number | null, nowOffsetMs: number): number {
  const [remaining, setRemaining] = useState(() => computeRemainingSeconds(targetOffsetMs, nowOffsetMs));
  const [trackedTarget, setTrackedTarget] = useState(targetOffsetMs);
  const [trackedNow, setTrackedNow] = useState(nowOffsetMs);
  if (trackedTarget !== targetOffsetMs || trackedNow !== nowOffsetMs) {
    setTrackedTarget(targetOffsetMs);
    setTrackedNow(nowOffsetMs);
    setRemaining(computeRemainingSeconds(targetOffsetMs, nowOffsetMs));
  }

  useEffect(() => {
    if (targetOffsetMs === null) return;
    const interval = setInterval(() => {
      setRemaining((previous) => Math.max(0, previous - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [targetOffsetMs, nowOffsetMs]);

  return remaining;
}

interface RoleTransitionScreenProps {
  session: SessionDetail;
  sessionId: string;
  roleLabel: string | undefined;
  userLabel: string | undefined;
  connectionStatus: ConnectionStatus;
  onContinued: () => Promise<void>;
}

function RoleTransitionScreen({ session, sessionId, roleLabel, userLabel, connectionStatus, onContinued }: RoleTransitionScreenProps) {
  const remainingSeconds = useCountdownSeconds(session.transition_continue_available_at_offset_ms, session.monotonic_offset_ms);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleContinue(): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      await continueToNextStage(sessionId);
      await onContinued();
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell title={t('operatorTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
      <div className="mx-auto flex max-w-md flex-col items-center gap-3 pt-12 text-center">
        <h1 className="font-heading text-lg font-medium">{t('operatorRoleTransitionTitle')}</h1>
        {remainingSeconds > 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('operatorRoleTransitionCountdownLabel')}: {remainingSeconds}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">{t('operatorRoleTransitionReady')}</p>
        )}
        <Button type="button" disabled={pending} onClick={() => void handleContinue()}>
          {t('operatorContinueButton')}
        </Button>
        {pending ? <p className="text-xs text-muted-foreground">{t('operatorRoleTransitionWaiting')}</p> : null}
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </div>
    </AppShell>
  );
}

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

export function OperatorConsolePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const userLabel = useAuthStore((state) => state.user?.display_name_ru);
  // D4: the header role chip is the signed-in account's role (Стажёр/Инструктор/Администратор),
  // not the simulation role — every authenticated page shows the same chip meaning.
  const userRole = useAuthStore((state) => state.user?.user_role);
  const roleLabel = userRole ? t(USER_ROLE_LABEL_KEY[userRole]) : undefined;
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
        // E10: the notifications panel (`NotificationsPlaceholder`) is a real panel now, fed the
        // same way the DDS console's own panel is.
        useNotificationStore.setState((state) => ({
          items: applyNotificationEvent(state.items, event, { incidentId: snapshot.session.incident_id }),
        }));
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
      <AppShell title={t('operatorTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('operatorConsoleLoading')}</p>
      </AppShell>
    );
  }

  if (snapshotQuery.isError) {
    const error = snapshotQuery.error;
    const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
    return (
      <AppShell title={t('operatorTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      </AppShell>
    );
  }

  const snapshot = snapshotQuery.data;
  if (!snapshot) {
    return null;
  }

  // E10: the session-wide transition screen — reached only through this trainee's own
  // complete_stage (whose response is a SessionDetail refetch drives us to see here), not
  // rendered from a locally-guessed stage_state.
  if (snapshot.session.state === 'ROLE_TRANSITION') {
    return (
      <RoleTransitionScreen
        session={snapshot.session}
        sessionId={sessionId}
        roleLabel={roleLabel}
        userLabel={userLabel}
        connectionStatus={connectionStatus}
        onContinued={async () => {
          const refreshed = await snapshotQuery.refetch();
          const role = refreshed.data?.my_role_type ?? refreshed.data?.active_role_type ?? null;
          if (role === 'DDS') {
            navigate(`/dds/${sessionId}`);
          } else if (role === null) {
            navigate('/sessions');
          }
        }}
      />
    );
  }

  if (snapshot.card === null) {
    return (
      <AppShell title={t('operatorTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <p className="text-sm text-muted-foreground">{t('operatorConsoleWrongRole')}</p>
      </AppShell>
    );
  }

  // E16: the link from the "session completed" state to the report (recon §6/§7) — a
  // COMPLETED/ABORTED session has nothing left to command here, only the report to view.
  if (snapshot.session.state === 'COMPLETED' || snapshot.session.state === 'ABORTED') {
    return (
      <AppShell title={t('operatorTitle')} role={roleLabel} userLabel={userLabel} connectionStatus={connectionStatus}>
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 pt-12 text-center">
          <p className="text-sm text-muted-foreground">{t('reportSessionCompletedNotice')}</p>
          <Button asChild size="sm">
            <Link to={`/report/${sessionId}`}>{t('reportViewReportButton')}</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  // I3 E3b (HLD 70 §70.5.2): a v2 schema is the one that gives fields an explicit layout `group`
  // — the same test `card-form.tsx` uses to pick its own layout.
  const isV2Card = snapshot.card.field_specs.some((spec) => spec.group !== null && spec.group !== undefined);

  return (
    <AppShell
      title={t('operatorTitle')}
      role={roleLabel}
      userLabel={userLabel}
      connectionStatus={connectionStatus}
    >
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr_320px]">
        <div className="flex flex-col gap-4">
          <PhoneWidget sessionId={sessionId} monotonicOffsetMs={snapshot.session.monotonic_offset_ms} />
          <StageActionBar sessionId={sessionId} onCommandNeedsRefresh={() => void snapshotQuery.refetch()} />
        </div>
        <div>
          {stageState === 'HANDOFF_PREPARATION' ? (
            <HandoffPreparationView sessionId={sessionId} monotonicOffsetMs={snapshot.session.monotonic_offset_ms} />
          ) : (
            <CardForm sessionId={sessionId} monotonicOffsetMs={snapshot.session.monotonic_offset_ms} />
          )}
        </div>
        <div className="flex flex-col gap-4">
          {/* I3 E3b: a v2 card embeds `ServicesPanel` itself as the reference's bottom services
              bar (`CardFormV2`) — rendering it again here would double-commit nothing (it is
              read-only display plus its own commands) but would show the same list twice. A v1
              card's `CardForm` never embeds it, so this sidebar keeps it exactly as before. */}
          {isV2Card ? null : <ServicesPanel sessionId={sessionId} />}
          <TranscriptPanel sessionId={sessionId} />
          <NotificationsPlaceholder sessionId={sessionId} />
        </div>
      </div>
    </AppShell>
  );
}
