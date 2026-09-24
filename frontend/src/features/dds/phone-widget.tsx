// The ДДС phone widget (I3 E6b, HLD 80 §80.3, §80.5; D25: `dds_brigade_call: ON` means "the ДДС
// workstation has a phone"). Rendered by the console only under `ON`; under `OFF` nothing of it
// exists (no button, no call). Every button comes from the server:
//
// * «Позвонить заявителю» only when the stage's `available_actions` offers `call_claimant`
//   (`startDdsCall {kind: CLAIMANT}`) and the line is free — the server still has the last word
//   (`409 DDS_LINE_BUSY`);
// * «Положить трубку» only from the call's own `DdsCallView.available_actions` (`hang_up`).
//
// The call's state is the server's `DdsCallView` — `listDdsCalls` on mount and on every
// `DDS_CALL_*` event (the console invalidates `queryKeys.dds.calls`), `startDdsCall` /
// `hangUpDdsCall` answers in between — held per `call_id` in `entities/call`'s `useDdsCallStore`.
// It never reads or writes the 112 call's `CallStateView` (80 §80.3.6).
//
// The media: the browser endpoint joins the call's own LiveKit room once the call is CONNECTED,
// with the token `startDdsCall` returned or — after a refresh (INV 13) — one `createVoiceToken
// {call_id}` mints, at most once per `call_id`, and leaves on ENDED or unmount; the same
// `CallMedia` the 112 widget uses. A media failure never blocks a REST command and never changes
// simulation state (SPEC §39): the call goes on without sound and the widget says so.
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { currentDdsCall, formatCallDurationMs, formatDialedRu, useDdsCallStore, type DdsCallView } from '@/entities/call';
import { useWorkItemStore } from '@/entities/work-item';
import {
  createDdsCallVoiceToken,
  hangUpDdsCall,
  listDdsCalls,
  problemMessageRu,
  queryKeys,
  startDdsCall,
  type ProblemCode,
  type VoiceTokenResponse,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { CallMedia, type MediaPhase } from '@/shared/media/call-media';

const STATE_LABEL_KEY: Record<DdsCallView['state'], keyof typeof ru> = {
  DIALING: 'ddsPhoneDialing',
  RINGING: 'ddsPhoneRinging',
  CONNECTED: 'ddsPhoneConnected',
  ENDED: 'ddsPhoneEnded',
};

const STATE_DOT_CLASS: Record<DdsCallView['state'], string> = {
  DIALING: 'animate-pulse bg-amber-500',
  RINGING: 'animate-pulse bg-amber-500',
  CONNECTED: 'bg-emerald-500',
  ENDED: 'bg-muted-foreground/40',
};

const PARTY_LABEL_KEY: Record<DdsCallView['kind'], keyof typeof ru> = {
  CLAIMANT: 'ddsPhonePartyClaimant',
  SERVICE_HEAD: 'ddsPhonePartyServiceHead',
  OPERATOR_112: 'ddsPhonePartyOperator112',
};

const END_REASON_LABEL_KEY: Record<NonNullable<DdsCallView['end_reason']>, keyof typeof ru> = {
  HANGUP: 'ddsPhoneEndReasonHangup',
  NO_ANSWER: 'ddsPhoneEndReasonNoAnswer',
  BUSY: 'ddsPhoneEndReasonBusy',
  ABORT: 'ddsPhoneEndReasonAbort',
  TRANSPORT_LOST: 'ddsPhoneEndReasonTransportLost',
};

function resolveLiveKitUrl(responseLiveKitUrl: string): string {
  const override = import.meta.env.VITE_LIVEKIT_URL as string | undefined;
  return override && override.length > 0 ? override : responseLiveKitUrl;
}

interface DdsPhoneWidgetProps {
  sessionId: string;
}

export function DdsPhoneWidget({ sessionId }: DdsPhoneWidgetProps) {
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const calls = useDdsCallStore((state) => state.calls);
  const call = currentDdsCall(calls);
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [mediaPhase, setMediaPhase] = useState<MediaPhase>('idle');

  const callsQuery = useQuery({ queryKey: queryKeys.dds.calls(sessionId), queryFn: () => listDdsCalls(sessionId) });
  useEffect(() => {
    if (callsQuery.data) useDdsCallStore.getState().setCalls(callsQuery.data);
  }, [callsQuery.data]);
  useEffect(() => () => useDdsCallStore.getState().reset(), []);

  // -- the media session (the 112 widget's `CallMedia`, one per widget lifetime) --------------
  const callMediaRef = useRef<CallMedia | null>(null);
  if (callMediaRef.current === null) {
    callMediaRef.current = new CallMedia({ onPhaseChange: setMediaPhase });
  }
  /** Tokens `startDdsCall` already returned, by `call_id` — a fresh call needs no second mint. */
  const tokensRef = useRef<Record<string, VoiceTokenResponse>>({});
  const joinedCallIdRef = useRef<string | null>(null);

  const liveCallId = call && call.state === 'CONNECTED' && call.endpoint === 'BROWSER' ? call.call_id : null;
  useEffect(() => {
    const media = callMediaRef.current;
    if (!media) return;
    if (liveCallId && joinedCallIdRef.current !== liveCallId) {
      joinedCallIdRef.current = liveCallId;
      void (async () => {
        try {
          const token = tokensRef.current[liveCallId] ?? (await createDdsCallVoiceToken(sessionId, liveCallId));
          await media.connect(resolveLiveKitUrl(token.livekit_url), token.token);
        } catch {
          setMediaPhase('failed');
        }
      })();
    } else if (!liveCallId && joinedCallIdRef.current !== null) {
      joinedCallIdRef.current = null;
      void media.disconnect();
    }
  }, [liveCallId, sessionId]);
  useEffect(() => () => void callMediaRef.current?.disconnect(), []);

  // -- the timer: from the server's own offsets, ticked locally while CONNECTED -----------------
  const [connectedMs, setConnectedMs] = useState(0);
  const [trackedCall, setTrackedCall] = useState<string | null>(null);
  const connectedCallId = call?.state === 'CONNECTED' ? call.call_id : null;
  if (trackedCall !== connectedCallId) {
    setTrackedCall(connectedCallId);
    setConnectedMs(0);
  }
  useEffect(() => {
    if (!connectedCallId) return;
    const id = setInterval(() => setConnectedMs((previous) => previous + 1000), 1000);
    return () => clearInterval(id);
  }, [connectedCallId]);

  function reportError(error: unknown): void {
    setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
  }

  async function handleCallClaimant(): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      const started = await startDdsCall(sessionId, { kind: 'CLAIMANT' });
      if (started.voice) tokensRef.current[started.call.call_id] = started.voice;
      useDdsCallStore.getState().upsertCall(started.call);
    } catch (error) {
      reportError(error);
    } finally {
      setPending(false);
    }
  }

  async function handleHangUp(callId: string): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      useDdsCallStore.getState().upsertCall(await hangUpDdsCall(sessionId, callId));
    } catch (error) {
      reportError(error);
    } finally {
      setPending(false);
    }
  }

  const lineFree = !call || call.state === 'ENDED';
  const callClaimant = lineFree ? (availableActions.find((action) => action.action_id === 'call_claimant') ?? null) : null;
  const hangUp = call?.available_actions.find((action) => action.action_id === 'hang_up') ?? null;
  const endedDurationMs =
    call?.state === 'ENDED' && call.answered_at_offset_ms !== null && call.ended_at_offset_ms !== null
      ? call.ended_at_offset_ms - call.answered_at_offset_ms
      : null;

  return (
    <section className="flex flex-wrap items-center gap-3 rounded-md border bg-card px-3 py-2 text-sm" data-slot="dds-phone-widget">
      <span className="font-medium">{t('ddsPhoneTitle')}</span>
      {call ? (
        <>
          <span className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${STATE_DOT_CLASS[call.state]}`} aria-hidden="true" />
            <span data-slot="dds-call-state">{t(STATE_LABEL_KEY[call.state])}</span>
          </span>
          <span data-slot="dds-call-party">{call.persona_title_ru ?? t(PARTY_LABEL_KEY[call.kind])}</span>
          <span className="text-muted-foreground" data-slot="dds-call-number">
            {t('ddsPhoneNumberLabel')}: {formatDialedRu(call.dialed)}
          </span>
          {call.state === 'CONNECTED' ? (
            <span className="font-mono" data-slot="dds-call-timer">
              {formatCallDurationMs(connectedMs)}
            </span>
          ) : null}
          {call.state === 'ENDED' ? (
            <span className="text-muted-foreground" data-slot="dds-call-end-reason">
              {call.end_reason ? t(END_REASON_LABEL_KEY[call.end_reason]) : null}
              {endedDurationMs !== null ? ` · ${formatCallDurationMs(endedDurationMs)}` : null}
            </span>
          ) : null}
        </>
      ) : (
        <span className="text-muted-foreground" data-slot="dds-call-state">
          {t('ddsPhoneIdle')}
        </span>
      )}
      <span className="flex flex-wrap gap-2">
        {callClaimant ? (
          <Button type="button" size="sm" disabled={pending} onClick={() => void handleCallClaimant()}>
            {callClaimant.label_ru}
          </Button>
        ) : null}
        {call && hangUp ? (
          <Button type="button" size="sm" variant="destructive" disabled={pending} onClick={() => void handleHangUp(call.call_id)}>
            {hangUp.label_ru}
          </Button>
        ) : null}
      </span>
      {liveCallId && mediaPhase === 'failed' ? (
        <p className="w-full text-xs text-amber-700" data-slot="dds-call-media-failed">
          {t('ddsPhoneMediaFailed')}
        </p>
      ) : null}
      {errorMessage ? (
        <p role="alert" className="w-full text-sm text-destructive">
          {errorMessage}
        </p>
      ) : null}
    </section>
  );
}
