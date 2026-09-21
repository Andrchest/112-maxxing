// The DDS status-update form (SPEC §11: "incident updates"). `send_status_update` is not a stage
// transition — it is offered in every DDS state from `ACKNOWLEDGED` through `RESOLVED`
// (`docs/hld/10-domain-model.md` §10.9) — so this form renders whenever `available_actions`
// includes it, regardless of the current stage_state.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useWorkItemStore, hasAvailableAction } from '@/entities/work-item';
import { sendDdsStatusUpdate, problemMessageRu, type ProblemCode, type StatusUpdateKind } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { STATUS_UPDATE_KIND_LABEL_KEY } from './dds-labels';

const STATUS_UPDATE_KINDS: readonly StatusUpdateKind[] = [
  'ACKNOWLEDGEMENT',
  'EN_ROUTE_REPORT',
  'ON_SCENE_REPORT',
  'SITUATION_UPDATE',
  'ADDITIONAL_FORCES_REQUESTED',
  'RESOLUTION_REPORT',
];

interface StatusUpdateFormProps {
  sessionId: string;
}

export function StatusUpdateForm({ sessionId }: StatusUpdateFormProps) {
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const canSend = hasAvailableAction(availableActions, 'send_status_update');
  const [kind, setKind] = useState<StatusUpdateKind>('SITUATION_UPDATE');
  const [text, setText] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(): Promise<void> {
    if (text.trim() === '') return;
    setErrorMessage(null);
    setPending(true);
    try {
      await sendDdsStatusUpdate(sessionId, { update_kind: kind, text_ru: text.trim() });
      setText('');
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  if (!canSend) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('ddsStatusUpdateTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <Label htmlFor="status-update-kind">{t('ddsStatusUpdateKindLabel')}</Label>
        <select
          id="status-update-kind"
          className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          value={kind}
          disabled={pending}
          onChange={(event) => setKind(event.target.value as StatusUpdateKind)}
        >
          {STATUS_UPDATE_KINDS.map((value) => (
            <option key={value} value={value}>
              {t(STATUS_UPDATE_KIND_LABEL_KEY[value] as keyof typeof ru)}
            </option>
          ))}
        </select>
        <Label htmlFor="status-update-text">{t('ddsStatusUpdateTextLabel')}</Label>
        <Textarea id="status-update-text" value={text} disabled={pending} onChange={(event) => setText(event.target.value)} />
        <Button type="button" disabled={pending || text.trim() === ''} onClick={() => void handleSubmit()}>
          {t('ddsStatusUpdateSubmit')}
        </Button>
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
