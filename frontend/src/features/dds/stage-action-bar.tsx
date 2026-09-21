// DDS stage transition buttons (SPEC §10/§11; D12 design decision #1). Strictly from
// `available_actions` — `select_resource`/`deselect_resource`/`dispatch`/`dispatch_additional`
// need a resource id and live in `resource-board.tsx`/`dispatch-tray.tsx`; `send_status_update`
// needs a form and lives in `status-update-form.tsx`; `close` needs a reason and lives in
// `close-dialog.tsx` (rendered alongside this bar by the console page). This bar renders only the
// simple, no-argument transitions: `acknowledge`, `open_resource_selection` (additive endpoint,
// landed after this epic's initial cut — offered in `ACKNOWLEDGED` and again, worded "Add more
// forces", in `DISPATCHED`/`EN_ROUTE`/`ARRIVED`/`WORKING` for additional dispatch — this bar never
// hard-codes which stage_state, it only ever renders what `available_actions` sends) and
// `back_to_acknowledged`.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { useWorkItemStore } from '@/entities/work-item';
import {
  acknowledgeDdsAssignment,
  openDdsResourceSelection,
  backToDdsAcknowledged,
  problemMessageRu,
  type ProblemCode,
  type DdsStageView,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { applyDdsStageView } from './apply-dds-stage-view';

type BarActionId = 'acknowledge' | 'open_resource_selection' | 'back_to_acknowledged';
const BAR_ACTION_IDS: readonly BarActionId[] = ['acknowledge', 'open_resource_selection', 'back_to_acknowledged'];

const BAR_ACTION_RUNNERS: Record<BarActionId, (sessionId: string) => Promise<DdsStageView>> = {
  acknowledge: acknowledgeDdsAssignment,
  open_resource_selection: openDdsResourceSelection,
  back_to_acknowledged: backToDdsAcknowledged,
};

interface StageActionBarProps {
  sessionId: string;
}

export function StageActionBar({ sessionId }: StageActionBarProps) {
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleClick(actionId: BarActionId): Promise<void> {
    setErrorMessage(null);
    setPendingActionId(actionId);
    try {
      applyDdsStageView(await BAR_ACTION_RUNNERS[actionId](sessionId));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingActionId(null);
    }
  }

  const visibleActions = availableActions.filter((action) => BAR_ACTION_IDS.includes(action.action_id as BarActionId));

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
            onClick={() => void handleClick(action.action_id as BarActionId)}
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
