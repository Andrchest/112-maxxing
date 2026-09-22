// The instructor's «Прервать сессию» control on the live overview (E20-E R11). `abortSession`
// (openapi.yaml) fires `abort` on the session machine (`CREATED|READY|ACTIVE|ROLE_TRANSITION ->
// ABORTED`) — the event log is preserved, never deleted (SPEC §39, §42 test 14), so this is a
// safe "end the exercise early" action, not a destructive one. INSTRUCTOR/ADMIN only (same gate
// `report-page.tsx`'s release control uses) and hidden once the session is already terminal
// (COMPLETED/ABORTED — `abortSession` itself refuses those with `409 INVALID_TRANSITION`, this
// only avoids offering a button the backend would refuse). Same confirm-dialog shape as
// `features/dds/close-dialog.tsx`: a required free-text field, the confirm button disabled until
// it is non-empty.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { abortSession, problemMessageRu, type ProblemCode, type SessionDetail } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

interface AbortSessionButtonProps {
  sessionId: string;
  onAborted: (session: SessionDetail) => void;
}

export function AbortSessionButton({ sessionId, onAborted }: AbortSessionButtonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleConfirm(): Promise<void> {
    const trimmed = reason.trim();
    if (trimmed === '') {
      setErrorMessage(t('instructorAbortReasonRequired'));
      return;
    }
    setErrorMessage(null);
    setPending(true);
    try {
      const session = await abortSession(sessionId, { reason: trimmed });
      onAborted(session);
      setOpen(false);
      setReason('');
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="destructive" size="sm">
          {t('instructorAbortButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('instructorAbortDialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="abort-reason">{t('instructorAbortReasonLabel')}</Label>
          <Textarea id="abort-reason" value={reason} disabled={pending} onChange={(event) => setReason(event.target.value)} />
          {errorMessage ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>
            {t('instructorAbortCancelButton')}
          </Button>
          <Button type="button" variant="destructive" disabled={pending || reason.trim() === ''} onClick={() => void handleConfirm()}>
            {t('instructorAbortConfirmButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
