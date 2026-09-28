// The phone widget (SPEC §32: "the caller's dialogue should primarily be experienced as a phone
// call, not as a giant chat window"; D12: "ringing, answer, timer, mute, hang-up, level meter").
// States come from `CallStateView.phase`; `answer`/`end_call` are rendered only when the server
// currently offers them (D12 design decision #1).
//
// E11-C: the LiveKit call itself goes live here (SPEC §15, D9). The widget joins the room only
// once the server reports CONNECTED (the `answer` command succeeded), using a token from
// `createVoiceToken` — never earlier, and it requests that token at most once per `call_id`. It
// leaves on ENDED, on unmount and therefore on route change too (this component only renders
// inside the operator console's normal layout; navigating away or entering ROLE_TRANSITION
// unmounts it). Mute is local-track mute only — never a backend command — and the level meter
// reads the local microphone via `shared/media/call-media.ts`'s `CallMedia`, never the caller's
// audio. A microphone permission failure never blocks a REST command (hang-up keeps working) and
// never changes simulation state (SPEC §39): it only shows a Russian message. A LiveKit reconnect
// shows the `operatorCallReconnecting` message (ru.ts) through `entities/call`'s own
// `useMediaStateStore` — a store fed exclusively by `CallMedia`'s callbacks, never by the
// application WebSocket (D9 DESIGN).
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { isSecureContext } from '@/shared/lib/secure-context';
import { useCallStateStore, type CallStateView } from '@/entities/session';
import { formatCallDurationMs, useMediaStateStore } from '@/entities/call';
import { useCardStore } from '@/entities/card';
import { useStageStore, type OperatorStageView } from '@/entities/stage';
import { answerCall, createVoiceToken, endCall, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { CallMedia } from '@/shared/media/call-media';

// Follow-up ruling (coordinator, after the HLD-gap flag in this task's report): the backend now
// mints `VoiceTokenResponse.livekit_url` as a browser-facing URL (its `livekit_public_url`
// setting, E11-B owns it), so that response is the normal source of truth. `VITE_LIVEKIT_URL`
// (see `.env.example`) is only a developer override — when set and non-empty it wins, but an
// unset/empty env var must never shadow the response.
function resolveLiveKitUrl(responseLiveKitUrl: string): string {
  const override = import.meta.env.VITE_LIVEKIT_URL as string | undefined;
  return override && override.length > 0 ? override : responseLiveKitUrl;
}

const PHASE_LABEL_KEY: Record<CallStateView['phase'], keyof typeof ru> = {
  NO_CALL: 'operatorPhoneNoCall',
  RINGING: 'operatorPhoneRinging',
  CONNECTED: 'operatorPhoneConnected',
  ENDED: 'operatorPhoneEnded',
};

const PHASE_DOT_CLASS: Record<CallStateView['phase'], string> = {
  NO_CALL: 'bg-muted-foreground/40',
  RINGING: 'animate-pulse bg-amber-500',
  CONNECTED: 'bg-emerald-500',
  ENDED: 'bg-muted-foreground/40',
};

interface PhoneWidgetProps {
  sessionId: string;
  /** `SessionDetail.monotonic_offset_ms` (server "now" as of the last snapshot fetch) — the
   * anchor {@link computeElapsedSinceMs} ticks from (D9). */
  monotonicOffsetMs: number;
}

/** D9: elapsed ms since `answeredAtOffsetMs`, both server offsets — never `Date.now()`, so a page
 * reload mid-call restores the real elapsed time instead of restarting at 0. */
function computeElapsedSinceMs(answeredAtOffsetMs: number | null, nowOffsetMs: number): number {
  return answeredAtOffsetMs === null ? 0 : Math.max(0, nowOffsetMs - answeredAtOffsetMs);
}

export function PhoneWidget({ sessionId, monotonicOffsetMs }: PhoneWidgetProps) {
  const callState = useCallStateStore((state) => state.callState);
  const availableActions = useStageStore((state) => state.availableActions);
  const answerAction = availableActions.find((action) => action.action_id === 'answer') ?? null;
  const endCallAction = availableActions.find((action) => action.action_id === 'end_call') ?? null;
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const phase = callState?.phase ?? 'NO_CALL';
  const answeredAtOffsetMs = callState?.answered_at_offset_ms ?? null;

  // D9: the call timer counts from the server's own `answered_at_offset_ms`, ticked locally
  // between snapshot refreshes from `monotonicOffsetMs` (DESIGN: no client clock authority beyond
  // ticking a counter between server refreshes, the same idiom the role-transition countdown in
  // `features/operator/console-page.tsx`'s `useCountdownSeconds` already uses). Reset during
  // render when a fresh pair arrives (React docs: "adjusting state when a prop changes"), not
  // inside the effect body, which only starts/stops the interval.
  const [connectedElapsedMs, setConnectedElapsedMs] = useState(() => computeElapsedSinceMs(answeredAtOffsetMs, monotonicOffsetMs));
  const [trackedAnsweredAt, setTrackedAnsweredAt] = useState(answeredAtOffsetMs);
  const [trackedNow, setTrackedNow] = useState(monotonicOffsetMs);
  if (trackedAnsweredAt !== answeredAtOffsetMs || trackedNow !== monotonicOffsetMs) {
    setTrackedAnsweredAt(answeredAtOffsetMs);
    setTrackedNow(monotonicOffsetMs);
    setConnectedElapsedMs(computeElapsedSinceMs(answeredAtOffsetMs, monotonicOffsetMs));
  }

  useEffect(() => {
    if (phase !== 'CONNECTED' || answeredAtOffsetMs === null) return;
    const id = setInterval(() => setConnectedElapsedMs((previous) => previous + 1000), 1000);
    return () => clearInterval(id);
  }, [phase, answeredAtOffsetMs]);

  // -- E11-C: the LiveKit media session (SPEC §15, D9) ----------------------------------------
  const mediaPhase = useMediaStateStore((state) => state.phase);
  const muted = useMediaStateStore((state) => state.muted);
  const level = useMediaStateStore((state) => state.level);
  const micPermissionDenied = useMediaStateStore((state) => state.micPermissionDenied);

  // One `CallMedia` per widget lifetime, created lazily during render the first time (React
  // docs: "How to create expensive objects lazily") — its callbacks only ever write to
  // `useMediaStateStore`, never to a store the application WebSocket also feeds (D9 DESIGN).
  const callMediaRef = useRef<CallMedia | null>(null);
  if (callMediaRef.current === null) {
    callMediaRef.current = new CallMedia({
      onPhaseChange: (nextPhase) => useMediaStateStore.getState().setPhase(nextPhase),
      onLevel: (nextLevel) => useMediaStateStore.getState().setLevel(nextLevel),
      onMicPermissionDenied: () => useMediaStateStore.getState().setMicPermissionDenied(true),
    });
  }

  // The call_id already joined (or left), so a re-render while the server is still CONNECTED
  // never re-requests a token (D9 DESIGN: "token requested once per join") and a refresh that
  // restores straight into CONNECTED (browser refresh mid-call) still joins exactly once.
  const joinedCallIdRef = useRef<string | null>(null);

  useEffect(() => {
    const media = callMediaRef.current;
    if (!media) return;
    // I6 HTTP: never join LiveKit over an insecure context — the answer button that could bring
    // the call to CONNECTED is hidden below, but this also covers a call already CONNECTED before
    // the page lost its secure context.
    if (!isSecureContext()) return;
    const callId = callState?.call_id ?? null;

    if (phase === 'CONNECTED' && callId && joinedCallIdRef.current !== callId) {
      joinedCallIdRef.current = callId;
      useMediaStateStore.getState().reset();
      void (async () => {
        try {
          const tokenResponse = await createVoiceToken(sessionId);
          await media.connect(resolveLiveKitUrl(tokenResponse.livekit_url), tokenResponse.token);
        } catch {
          // A token/join failure never blocks a REST command (SPEC §39) — the call stays
          // controllable through `answer`/`end_call`; only the media phase reflects it.
          useMediaStateStore.getState().setPhase('failed');
        }
      })();
    } else if (phase !== 'CONNECTED' && joinedCallIdRef.current !== null) {
      joinedCallIdRef.current = null;
      void media.disconnect();
    }
  }, [phase, callState?.call_id, sessionId]);

  // Leaves the room on unmount — covers both this component going away on ENDED-driven
  // navigation and a plain route change away from the operator console (D9 DESIGN).
  useEffect(() => {
    return () => {
      void callMediaRef.current?.disconnect();
    };
  }, []);

  function handleToggleMute(): void {
    const nextMuted = !muted;
    useMediaStateStore.getState().setMuted(nextMuted);
    callMediaRef.current?.setMuted(nextMuted);
  }

  function applyStageView(view: OperatorStageView): void {
    useStageStore.getState().setFromStageView(view);
    useCardStore.getState().setCard(view.card);
    useCallStateStore.getState().setCallState(view.call_state);
  }

  async function handleAnswer(): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      applyStageView(await answerCall(sessionId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  async function handleHangup(): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      applyStageView(await endCall(sessionId, { reason: 'OPERATOR_HANGUP' }));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  const durationMs = callState?.duration_ms ?? connectedElapsedMs;
  const secure = isSecureContext();

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorPhoneTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!secure ? (
          <p className="text-sm text-muted-foreground" data-slot="operator-phone-insecure-notice">
            {t('secureContextRequiredNotice')}
          </p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className={`size-2.5 rounded-full ${PHASE_DOT_CLASS[phase]}`} aria-hidden="true" />
              <span className="text-sm font-medium" data-slot="call-phase">
                {t(PHASE_LABEL_KEY[phase])}
              </span>
            </div>
            {callState?.caller_display_ru ? (
              <p className="text-sm text-muted-foreground">{callState.caller_display_ru}</p>
            ) : null}
            {phase === 'CONNECTED' || (phase === 'ENDED' && callState?.duration_ms != null) ? (
              <p className="font-mono text-lg" data-slot="call-timer">
                {formatCallDurationMs(durationMs)}
              </p>
            ) : null}
            {callState?.caller_speaking ? (
              <p className="text-xs text-emerald-600" data-slot="caller-speaking">
                {t('operatorCallerSpeaking')}
              </p>
            ) : null}
            {mediaPhase === 'reconnecting' ? (
              <p className="text-xs text-amber-600" data-slot="media-reconnecting">
                {t('operatorCallReconnecting')}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
              {answerAction ? (
                <Button type="button" disabled={pending} onClick={() => void handleAnswer()}>
                  {answerAction.label_ru}
                </Button>
              ) : null}
              {/* D11: once the call itself has ended (`CallStateView.phase === 'ENDED'`), never
                  offer to end it again — even if the stage's own `available_actions` still lists
                  `end_call` for a moment (e.g. before the next snapshot refresh). */}
              {endCallAction && phase !== 'ENDED' ? (
                <Button type="button" variant="destructive" disabled={pending} onClick={() => void handleHangup()}>
                  {endCallAction.label_ru}
                </Button>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={mediaPhase === 'idle' || mediaPhase === 'failed'}
                aria-pressed={muted}
                onClick={handleToggleMute}
              >
                {muted ? t('operatorUnmuteButton') : t('operatorMuteButton')}
              </Button>
              <span className="text-xs text-muted-foreground" data-slot="level-meter">
                {t('operatorLevelMeterLabel')}: {mediaPhase === 'connected' ? Math.round(level * 100) : '—'}
              </span>
            </div>
            {micPermissionDenied ? (
              <p role="alert" className="text-sm text-destructive" data-slot="mic-permission-denied">
                {t('operatorMicPermissionDenied')}
              </p>
            ) : null}
          </>
        )}
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
