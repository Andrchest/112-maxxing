// The selection tray + dispatch command, and the live status of already-dispatched units (SPEC
// §11). `dispatch` (first time) and `dispatch_additional` (`DISPATCHED`/`EN_ROUTE`/`ARRIVED`/
// `WORKING` — per the manager rulings this task was briefed with) share the same
// `dispatchDdsResources` endpoint; `DispatchResultView.is_additional` only tells them apart after
// the fact. Which one is offered right now is decided entirely by `available_actions` — this
// component never infers it from `stage_state`.
import { useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { useResourceStore } from '@/entities/resource';
import { useWorkItemStore, hasAvailableAction } from '@/entities/work-item';
import { dispatchDdsResources, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { applyDdsStageView } from './apply-dds-stage-view';
import { resourceStatusLabelRu } from './dds-labels';

interface DispatchTrayProps {
  sessionId: string;
}

export function DispatchTray({ sessionId }: DispatchTrayProps) {
  const resources = useResourceStore((state) => state.resources);
  const workItem = useWorkItemStore((state) => state.workItem);
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const canDispatch = hasAvailableAction(availableActions, 'dispatch') || hasAvailableAction(availableActions, 'dispatch_additional');
  const dispatchLabelKey = hasAvailableAction(availableActions, 'dispatch_additional') ? 'ddsDispatchAdditionalButton' : 'ddsDispatchButton';
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const selectedIds = new Set(workItem?.selected_resource_ids ?? []);
  const dispatchedIds = new Set(workItem?.dispatched_resource_ids ?? []);
  const selected = resources.filter((resource) => selectedIds.has(resource.resource_id));
  const dispatched = resources.filter((resource) => dispatchedIds.has(resource.resource_id));

  async function handleDispatch(): Promise<void> {
    setErrorMessage(null);
    setPending(true);
    try {
      const result = await dispatchDdsResources(sessionId, note.trim() === '' ? {} : { note_ru: note.trim() });
      applyDdsStageView(result.stage);
      setNote('');
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsSelectionTrayTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {selected.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('ddsSelectionTrayEmpty')}</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {selected.map((resource) => (
              <Badge key={resource.resource_id} variant="secondary">
                {resource.callsign}
              </Badge>
            ))}
          </ul>
        )}
        {canDispatch ? (
          <div className="flex flex-col gap-2">
            <Textarea
              placeholder={t('ddsDispatchNoteLabel')}
              value={note}
              disabled={pending}
              onChange={(event) => setNote(event.target.value)}
            />
            <Button type="button" disabled={pending || selected.length === 0} onClick={() => void handleDispatch()}>
              {t(dispatchLabelKey)}
            </Button>
          </div>
        ) : null}
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}

        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{t('ddsDispatchedUnitsTitle')}</h3>
          {dispatched.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('ddsDispatchedUnitsEmpty')}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {dispatched.map((resource) => (
                <li key={resource.resource_id} className="flex items-center justify-between gap-2 text-sm">
                  <span>{resource.callsign}</span>
                  <Badge variant="outline">{resourceStatusLabelRu(resource.current_status)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
