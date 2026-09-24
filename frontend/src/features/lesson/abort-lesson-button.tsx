// I3 E4b (70 §70.3.2): aborts the lesson and every non-terminal card session
// (`CREATED|ACTIVE -> ABORTED`). Same confirm-dialog shape `features/instructor/abort-session-
// button.tsx` uses for a single session — a required free-text reason, confirm disabled until it
// is non-empty.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { abortLesson, problemMessageRu, type LessonDetail, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

interface AbortLessonButtonProps {
  lessonId: string;
  onAborted: (lesson: LessonDetail) => void;
}

export function AbortLessonButton({ lessonId, onAborted }: AbortLessonButtonProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleConfirm(): Promise<void> {
    const trimmed = reason.trim();
    if (trimmed === '') {
      setErrorMessage(t('lessonDetailAbortReasonRequired'));
      return;
    }
    setErrorMessage(null);
    setPending(true);
    try {
      const lesson = await abortLesson(lessonId, { reason: trimmed });
      onAborted(lesson);
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
          {t('lessonDetailAbortButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('lessonDetailAbortDialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="lesson-abort-reason">{t('lessonDetailAbortReasonLabel')}</Label>
          <Textarea
            id="lesson-abort-reason"
            value={reason}
            disabled={pending}
            onChange={(event) => setReason(event.target.value)}
          />
          {errorMessage ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>
            {t('lessonDetailAbortCancelButton')}
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={pending || reason.trim() === ''}
            onClick={() => void handleConfirm()}
          >
            {t('lessonDetailAbortConfirmButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
