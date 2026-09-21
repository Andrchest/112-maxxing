// Stage transition buttons (SPEC §9/§10; D12 design decision #1). `answer`/`end_call` are the
// phone widget's own buttons (SPEC §32: they belong to "the phone call", not a generic action
// bar) — this bar renders every OTHER action the server currently offers, strictly from
// `available_actions`. `create_handoff` and `complete_stage` are rendered here (their buttons
// come from the server like any other action) but wired to a TODO(E10) toast instead of a real
// command, per this task's brief: E10 wires them once the DDS backend exists.
import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { useCardStore } from '@/entities/card';
import { useCallStateStore } from '@/entities/session';
import { useStageStore, type OperatorStageView } from '@/entities/stage';
import {
  backToInterview,
  beginHandoffPreparation,
  problemMessageRu,
  type ProblemCode,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

type BarActionId = 'open_handoff_preparation' | 'back_to_interview';
const BAR_ACTION_IDS: readonly BarActionId[] = ['open_handoff_preparation', 'back_to_interview'];
const NOT_YET_AVAILABLE_ACTION_IDS = new Set(['create_handoff', 'complete_stage']);

function runBarAction(sessionId: string, actionId: BarActionId): Promise<OperatorStageView> {
  return actionId === 'open_handoff_preparation'
    ? beginHandoffPreparation(sessionId)
    : backToInterview(sessionId);
}

interface StageActionBarProps {
  sessionId: string;
}

export function StageActionBar({ sessionId }: StageActionBarProps) {
  const availableActions = useStageStore((state) => state.availableActions);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  function applyStageView(view: OperatorStageView): void {
    useStageStore.getState().setFromStageView(view);
    useCardStore.getState().setCard(view.card);
    useCallStateStore.getState().setCallState(view.call_state);
  }

  async function handleClick(actionId: string): Promise<void> {
    setErrorMessage(null);
    if (NOT_YET_AVAILABLE_ACTION_IDS.has(actionId)) {
      // TODO(E10): wire createHandoff/completeOperatorStage once the DDS backend exists.
      toast(t('operatorActionNotYetAvailable'));
      return;
    }
    if (!BAR_ACTION_IDS.includes(actionId as BarActionId)) {
      return;
    }
    setPendingActionId(actionId);
    try {
      applyStageView(await runBarAction(sessionId, actionId as BarActionId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingActionId(null);
    }
  }

  const visibleActions = availableActions.filter(
    (action) => BAR_ACTION_IDS.includes(action.action_id as BarActionId) || NOT_YET_AVAILABLE_ACTION_IDS.has(action.action_id),
  );

  if (visibleActions.length === 0 && errorMessage === null) {
    return null;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {visibleActions.map((action) => (
          <Button
            key={action.action_id}
            type="button"
            variant="outline"
            disabled={pendingActionId !== null}
            onClick={() => void handleClick(action.action_id)}
          >
            {action.label_ru}
          </Button>
        ))}
      </div>
      {errorMessage ? (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
