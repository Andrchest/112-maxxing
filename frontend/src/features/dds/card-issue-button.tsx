// I3 E5b/E5c — «Отметить ошибку в карточке», offered only under `dds_card_check: ON` (70 §70.4.4,
// §70.7, C1) — in memo `ACKNOWLEDGED`, and in picker from `ACKNOWLEDGED` to `RESOLVED` (the
// manager's E5b follow-up ruling). Gated purely by `available_actions` (`flag_card_issue`), same
// as every other DDS command — this button renders in both `dds_mode` variants without branching
// on the mode itself.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useWorkItemStore, hasAvailableAction } from '@/entities/work-item';
import { flagDdsCardIssue, listDdsLegs, problemMessageRu, queryKeys, type CardIssueKind, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { CARD_ISSUE_KIND_LABEL_KEY } from './dds-labels';

const CARD_ISSUE_KINDS: readonly CardIssueKind[] = ['MISSING', 'WRONG', 'CONTRADICTION', 'OTHER'];

interface CardIssueButtonProps {
  sessionId: string;
}

export function CardIssueButton({ sessionId }: CardIssueButtonProps) {
  const availableActions = useWorkItemStore((state) => state.availableActions);
  const canFlag = hasAvailableAction(availableActions, 'flag_card_issue');
  const legsQuery = useQuery({ queryKey: queryKeys.dds.legs(sessionId), queryFn: () => listDdsLegs(sessionId), enabled: canFlag });
  const [open, setOpen] = useState(false);
  const [assignmentId, setAssignmentId] = useState('');
  const [issueKind, setIssueKind] = useState<CardIssueKind>('WRONG');
  const [fieldPath, setFieldPath] = useState('');
  const [comment, setComment] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const legs = legsQuery.data ?? [];

  async function handleSubmit(): Promise<void> {
    if (assignmentId === '') return;
    if (comment.trim() === '') {
      setErrorMessage(t('ddsCardIssueCommentRequiredNotice'));
      return;
    }
    setErrorMessage(null);
    setPending(true);
    try {
      await flagDdsCardIssue(sessionId, {
        assignment_id: assignmentId,
        issue_kind: issueKind,
        field_path: fieldPath.trim() === '' ? null : fieldPath.trim(),
        comment_ru: comment.trim(),
      });
      setOpen(false);
      setAssignmentId('');
      setFieldPath('');
      setComment('');
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  if (!canFlag) {
    return null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline">
          {t('ddsCardIssueButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('ddsCardIssueDialogTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="card-issue-service">{t('ddsCardIssueServiceLabel')}</Label>
          <select
            id="card-issue-service"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={assignmentId}
            disabled={pending}
            onChange={(event) => setAssignmentId(event.target.value)}
          >
            <option value=""></option>
            {legs.map((leg) => (
              <option key={leg.assignment_id} value={leg.assignment_id}>
                {leg.service_name_ru}
              </option>
            ))}
          </select>
          <Label htmlFor="card-issue-kind">{t('ddsCardIssueKindLabel')}</Label>
          <select
            id="card-issue-kind"
            className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={issueKind}
            disabled={pending}
            onChange={(event) => setIssueKind(event.target.value as CardIssueKind)}
          >
            {CARD_ISSUE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(CARD_ISSUE_KIND_LABEL_KEY[kind] as keyof typeof ru)}
              </option>
            ))}
          </select>
          <Label htmlFor="card-issue-field">{t('ddsCardIssueFieldPathLabel')}</Label>
          <Input id="card-issue-field" value={fieldPath} disabled={pending} onChange={(event) => setFieldPath(event.target.value)} />
          <Label htmlFor="card-issue-comment">{t('ddsCardIssueCommentLabel')}</Label>
          <Textarea id="card-issue-comment" value={comment} disabled={pending} onChange={(event) => setComment(event.target.value)} />
          {errorMessage ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>
            {t('ddsCardIssueCancelButton')}
          </Button>
          <Button type="button" disabled={pending || assignmentId === ''} onClick={() => void handleSubmit()}>
            {t('ddsCardIssueSubmitButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
