// Stage transition buttons (SPEC §9/§10; D12 design decision #1). `answer`/`end_call` are the
// phone widget's own buttons (SPEC §32: they belong to "the phone call", not a generic action
// bar) — this bar renders every OTHER action the server currently offers, strictly from
// `available_actions`.
//
// `create_handoff` and `complete_stage` (E10) both return a shape narrower than
// `OperatorStageView` (`HandoffCreatedView`/`SessionDetail` — no `available_actions`/`card`/
// `call_state`), so instead of hand-assembling a fake stage view from a partial response, both
// call `onCommandNeedsRefresh` and let the console page's existing snapshot re-fetch (already
// wired to `STAGE_STATE_CHANGED`/`HANDOFF_CREATED`, D12 design decision #1: "the view is replaced
// by the server's response" — a re-fetch is still that, just triggered proactively instead of
// reactively) pick up the authoritative `available_actions`/`card`/`call_state` afterwards.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { useCardStore } from '@/entities/card';
import { useCallStateStore } from '@/entities/session';
import { useStageStore, type OperatorStageView } from '@/entities/stage';
import {
  backToInterview,
  beginHandoffPreparation,
  completeOperatorStage,
  createHandoff,
  problemMessageRu,
  type ProblemCode,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

type BarActionId = 'open_handoff_preparation' | 'back_to_interview';
const BAR_ACTION_IDS: readonly BarActionId[] = ['open_handoff_preparation', 'back_to_interview'];

function runBarAction(sessionId: string, actionId: BarActionId): Promise<OperatorStageView> {
  return actionId === 'open_handoff_preparation'
    ? beginHandoffPreparation(sessionId)
    : backToInterview(sessionId);
}

interface StageActionBarProps {
  sessionId: string;
  /** Called after `create_handoff`/`complete_stage` succeed — see the module comment. */
  onCommandNeedsRefresh?: () => void;
}

export function StageActionBar({ sessionId, onCommandNeedsRefresh }: StageActionBarProps) {
  const availableActions = useStageStore((state) => state.availableActions);
  const createHandoffAction = availableActions.find((action) => action.action_id === 'create_handoff') ?? null;
  const completeStageAction = availableActions.find((action) => action.action_id === 'complete_stage') ?? null;
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [handoffDialogOpen, setHandoffDialogOpen] = useState(false);
  const [handoffComment, setHandoffComment] = useState('');

  function applyStageView(view: OperatorStageView): void {
    useStageStore.getState().setFromStageView(view);
    useCardStore.getState().setCard(view.card);
    useCallStateStore.getState().setCallState(view.call_state);
  }

  async function handleClick(actionId: string): Promise<void> {
    if (!BAR_ACTION_IDS.includes(actionId as BarActionId)) {
      return;
    }
    setErrorMessage(null);
    setPendingActionId(actionId);
    try {
      applyStageView(await runBarAction(sessionId, actionId as BarActionId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleCreateHandoff(): Promise<void> {
    setErrorMessage(null);
    setPendingActionId('create_handoff');
    try {
      await createHandoff(sessionId, { comment_ru: handoffComment.trim() === '' ? null : handoffComment.trim() });
      setHandoffDialogOpen(false);
      setHandoffComment('');
      onCommandNeedsRefresh?.();
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleCompleteStage(): Promise<void> {
    setErrorMessage(null);
    setPendingActionId('complete_stage');
    try {
      await completeOperatorStage(sessionId);
      onCommandNeedsRefresh?.();
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingActionId(null);
    }
  }

  const visibleActions = availableActions.filter((action) => BAR_ACTION_IDS.includes(action.action_id as BarActionId));

  if (visibleActions.length === 0 && !createHandoffAction && !completeStageAction && errorMessage === null) {
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
        {createHandoffAction ? (
          <Dialog open={handoffDialogOpen} onOpenChange={setHandoffDialogOpen}>
            <DialogTrigger asChild>
              <Button type="button" variant="outline" disabled={pendingActionId !== null}>
                {createHandoffAction.label_ru}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t('operatorCreateHandoffDialogTitle')}</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-2">
                <Label htmlFor="handoff-comment">{t('operatorHandoffCommentLabel')}</Label>
                <Textarea
                  id="handoff-comment"
                  value={handoffComment}
                  disabled={pendingActionId !== null}
                  onChange={(event) => setHandoffComment(event.target.value)}
                />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" disabled={pendingActionId !== null} onClick={() => setHandoffDialogOpen(false)}>
                  {t('operatorCreateHandoffCancelButton')}
                </Button>
                <Button type="button" disabled={pendingActionId !== null} onClick={() => void handleCreateHandoff()}>
                  {t('operatorCreateHandoffConfirmButton')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        ) : null}
        {completeStageAction ? (
          <Button type="button" variant="outline" disabled={pendingActionId !== null} onClick={() => void handleCompleteStage()}>
            {completeStageAction.label_ru}
          </Button>
        ) : null}
      </div>
      {errorMessage ? (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
