// The DDS incident-close dialog (SPEC §11: "closure"). `closeDdsIncident` requires a
// `ClosureReason` (openapi.yaml `CloseIncidentRequest.closure_reason` is required, `comment_ru`
// is not) — the confirm button stays disabled until a reason is chosen, so the trainee can never
// send a request the backend would reject for a missing reason it is this form's own job to
// collect. Closing the last stage completes the session and runs scoring (SPEC §11) — this
// component only issues the command; the console page picks up the resulting session/stage state
// from the next snapshot refresh (`STAGE_STATE_CHANGED`/`DDS_INCIDENT_CLOSED`), same as every
// other DDS command.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { Hint } from '@/shared/ui/tour';
import { ru } from '@/shared/i18n/ru';
import { useWorkItemStore, hasAvailableAction } from '@/entities/work-item';
import { closeDdsIncident, problemMessageRu, type ProblemCode, type ClosureReason } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { CLOSURE_REASON_LABEL_KEY } from './dds-labels';

const CLOSURE_REASONS: readonly ClosureReason[] = ['RESOLVED', 'FALSE_CALL', 'TRANSFERRED', 'CANCELLED_BY_CALLER'];

interface CloseDialogProps {
  sessionId: string;
}

export function CloseDialog({ sessionId }: CloseDialogProps) {
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const canClose = hasAvailableAction(availableActions, 'close');
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ClosureReason | ''>('');
  const [comment, setComment] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleConfirm(): Promise<void> {
    if (reason === '') {
      setErrorMessage(t('ddsCloseReasonRequired'));
      return;
    }
    setErrorMessage(null);
    setPending(true);
    try {
      const session = await closeDdsIncident(sessionId, { closure_reason: reason, comment_ru: comment.trim() === '' ? null : comment.trim() });
      useWorkItemStore.setState({ sessionState: session.state });
      setOpen(false);
      setReason('');
      setComment('');
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  if (!canClose) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          {t('ddsCloseButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('ddsCloseDialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1.5">
            <Label htmlFor="close-reason">{t('ddsCloseReasonLabel')}</Label>
            <Hint text={t('hintDdsCloseReason')} />
          </div>
          <select
            id="close-reason"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={reason}
            disabled={pending}
            onChange={(event) => setReason(event.target.value as ClosureReason)}
          >
            <option value=""></option>
            {CLOSURE_REASONS.map((value) => (
              <option key={value} value={value}>
                {t(CLOSURE_REASON_LABEL_KEY[value] as keyof typeof ru)}
              </option>
            ))}
          </select>
          <Label htmlFor="close-comment">{t('ddsCloseCommentLabel')}</Label>
          <Textarea id="close-comment" value={comment} disabled={pending} onChange={(event) => setComment(event.target.value)} />
          {errorMessage ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>
            {t('ddsCloseCancelButton')}
          </Button>
          <Button type="button" disabled={pending || reason === ''} onClick={() => void handleConfirm()}>
            {t('ddsCloseConfirmButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
