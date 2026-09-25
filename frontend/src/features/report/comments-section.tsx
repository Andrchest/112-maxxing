// «Комментарии преподавателя» (I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶236, ¶237). Instructor
// feedback on a session's result. The trainee sees this section exactly when the report itself is
// visible to them — `report-page.tsx` never renders it unless the report query already succeeded,
// which is the same `report_visibility` gate the backend applies to `listSessionComments`.
//
// An edit is a new row, never an update (append-only, `replaces_comment_id`): «Изменить» opens the
// same add form pre-filled with the current text and submits with `replaces_comment_id` set. A
// superseded row stays visible, marked, so nothing in the record disappears.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Badge } from '@/shared/ui/badge';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import {
  createSessionComment,
  listSessionComments,
  problemMessageRu,
  queryKeys,
  type ProblemCode,
  type ResultCommentView,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';

interface CommentsSectionProps {
  sessionId: string;
  canManage: boolean;
}

export function CommentsSection({ sessionId, canManage }: CommentsSectionProps) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<ResultCommentView | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const commentsQuery = useQuery({
    queryKey: queryKeys.reports.comments(sessionId),
    queryFn: () => listSessionComments(sessionId),
    retry: false,
  });

  const submit = useMutation({
    mutationFn: (text: string) =>
      createSessionComment(sessionId, {
        text,
        replaces_comment_id: editing?.comment_id ?? null,
      }),
    onSuccess: async () => {
      setDraft('');
      setEditing(null);
      setSubmitError(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.reports.comments(sessionId) });
    },
    onError: (error: unknown) => {
      setSubmitError(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    },
  });

  function startEdit(comment: ResultCommentView): void {
    setEditing(comment);
    setDraft(comment.text);
    setSubmitError(null);
  }

  function cancelEdit(): void {
    setEditing(null);
    setDraft('');
    setSubmitError(null);
  }

  const comments = commentsQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportCommentsTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {commentsQuery.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {commentsQuery.error instanceof ProblemError ? problemMessageRu(commentsQuery.error.code as ProblemCode) : t('problemUnknown')}
          </p>
        ) : comments.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportCommentsEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {comments.map((comment) => (
              <li key={comment.comment_id} className="rounded-md border border-border p-2 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{comment.author_display_name_ru}</span>
                  <span>{formatTimestampRu(comment.created_at)}</span>
                  {comment.superseded ? <Badge variant="outline">{t('reportCommentsSupersededBadge')}</Badge> : null}
                </div>
                <p className="mt-1 whitespace-pre-wrap">{comment.text}</p>
                {canManage && !comment.superseded ? (
                  <div className="mt-1">
                    <Button type="button" variant="ghost" size="sm" onClick={() => startEdit(comment)}>
                      {t('reportCommentsEditButton')}
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        {canManage ? (
          <div className="flex flex-col gap-2 border-t border-border pt-2">
            {editing ? <p className="text-xs text-muted-foreground">{t('reportCommentsEditedFromLabel')}</p> : null}
            <Textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t('reportCommentsAddPlaceholder')}
              disabled={submit.isPending}
            />
            {submitError ? (
              <p role="alert" className="text-xs text-destructive">
                {submitError}
              </p>
            ) : null}
            <div className="flex items-center gap-2">
              <Button
                type="button"
                size="sm"
                disabled={submit.isPending || draft.trim().length === 0}
                onClick={() => submit.mutate(draft.trim())}
              >
                {submit.isPending ? t('reportCommentsSavingButton') : t('reportCommentsAddButton')}
              </Button>
              {editing ? (
                <Button type="button" variant="ghost" size="sm" disabled={submit.isPending} onClick={cancelEdit}>
                  {t('reportCommentsCancelButton')}
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
