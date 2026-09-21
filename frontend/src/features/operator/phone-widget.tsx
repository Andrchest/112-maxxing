// The phone widget (SPEC §32: "the caller's dialogue should primarily be experienced as a phone
// call, not as a giant chat window"; D12: "ringing, answer, timer, mute, hang-up, level meter").
// States come from `CallStateView.phase`; `answer`/`end_call` are rendered only when the server
// currently offers them (D12 design decision #1). Mute and the level meter are visually present
// but inert — LiveKit audio arrives in E11 (SPEC §15, D9).
import { useEffect, useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useCallStateStore, type CallStateView } from '@/entities/session';
import { formatCallDurationMs } from '@/entities/call';
import { useCardStore } from '@/entities/card';
import { useStageStore, type OperatorStageView } from '@/entities/stage';
import { answerCall, endCall, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

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
}

export function PhoneWidget({ sessionId }: PhoneWidgetProps) {
  const callState = useCallStateStore((state) => state.callState);
  const availableActions = useStageStore((state) => state.availableActions);
  const answerAction = availableActions.find((action) => action.action_id === 'answer') ?? null;
  const endCallAction = availableActions.find((action) => action.action_id === 'end_call') ?? null;
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const phase = callState?.phase ?? 'NO_CALL';
  // Elapsed wall-clock ms since the widget observed CONNECTED — a display-only best-effort timer
  // (SPEC §32: "timer"); `Date.now()` only ever runs inside the effect/interval callback, never
  // in the render body, so render itself only ever reads plain state.
  const [connectedElapsedMs, setConnectedElapsedMs] = useState(0);
  // Reset during render on a phase change (React docs: "Adjusting state when a prop changes"),
  // not inside the effect body below, which only starts/stops the interval.
  const [phaseAtLastRender, setPhaseAtLastRender] = useState(phase);
  if (phase !== phaseAtLastRender) {
    setPhaseAtLastRender(phase);
    if (phase !== 'CONNECTED') {
      setConnectedElapsedMs(0);
    }
  }

  useEffect(() => {
    if (phase !== 'CONNECTED') return;
    const startedAtWallClock = Date.now();
    const id = setInterval(() => setConnectedElapsedMs(Date.now() - startedAtWallClock), 1000);
    return () => clearInterval(id);
  }, [phase]);

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

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorPhoneTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
        <div className="flex flex-wrap items-center gap-2">
          {answerAction ? (
            <Button type="button" disabled={pending} onClick={() => void handleAnswer()}>
              {answerAction.label_ru}
            </Button>
          ) : null}
          {endCallAction ? (
            <Button type="button" variant="destructive" disabled={pending} onClick={() => void handleHangup()}>
              {endCallAction.label_ru}
            </Button>
          ) : null}
          {/* TODO(E11): mute + level meter go live with LiveKit audio (SPEC §15, D9); inert until then. */}
          <Button type="button" variant="outline" size="sm" disabled>
            {t('operatorMuteButton')}
          </Button>
          <span className="text-xs text-muted-foreground" data-slot="level-meter">
            {t('operatorLevelMeterLabel')}: —
          </span>
        </div>
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
