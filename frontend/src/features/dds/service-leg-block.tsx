// I3 E5c (manager review): one notified service's tab in the bottom «Службы:» bar (70 §70.4.3,
// REQ-5294/5295; ref/screenshot-dds/image6.png, image9.png, image20.png). The tab itself shows the
// service and its last status + time; clicking it (there is no separate chevron control — the
// whole tab toggles, same accessible affordance the reference's "^" offers) opens a popup that
// grows UPWARD from the tab (`absolute bottom-full`) holding the history (author, time, «Номер
// наряда», comment) and, when `leg.is_mine`, the pencil. The pencil form's dropdown is
// `leg.available_actions` verbatim — never a hard-coded status list — and its confirm/cancel are
// icon buttons (✓/×) carrying the same accessible names (`aria-label`) the buttons always had, so
// existing and new tests keep finding them by role+name.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Textarea } from '@/shared/ui/textarea';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import { problemMessageRu, setDdsServiceStatus, type DdsLegView, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { serviceResponseStatusLabelRu, TRIGGER_TARGET_STATUS, triggerRequiresComment } from './dds-labels';

interface ServiceLegBlockProps {
  sessionId: string;
  leg: DdsLegView;
  expanded: boolean;
  onToggle: () => void;
  onLegUpdated: (leg: DdsLegView) => void;
}

export function ServiceLegBlock({ sessionId, leg, expanded, onToggle, onLegUpdated }: ServiceLegBlockProps) {
  const [editing, setEditing] = useState(false);
  const [trigger, setTrigger] = useState('');
  const [orderNumber, setOrderNumber] = useState('');
  const [comment, setComment] = useState('');
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const canEdit = leg.is_mine && leg.available_actions.length > 0;
  const commentRequired = triggerRequiresComment(trigger);

  function openEditor(): void {
    setTrigger(leg.available_actions[0]?.action_id ?? '');
    setOrderNumber('');
    setComment('');
    setErrorMessage(null);
    setEditing(true);
  }

  async function handleSubmit(): Promise<void> {
    if (trigger === '') return;
    if (commentRequired && comment.trim() === '') {
      setErrorMessage(t('ddsLegCommentRequiredNotice'));
      return;
    }
    const targetStatus = TRIGGER_TARGET_STATUS[trigger];
    if (!targetStatus) return;
    setErrorMessage(null);
    setPending(true);
    try {
      const updated = await setDdsServiceStatus(sessionId, leg.assignment_id, {
        status: targetStatus,
        order_number: orderNumber.trim() === '' ? null : orderNumber.trim(),
        comment_ru: comment.trim() === '' ? null : comment.trim(),
      });
      onLegUpdated(updated);
      setEditing(false);
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="relative" data-slot="dds-leg-tab">
      {/* I3 E7a (manager review): the tab's own text must set its own colour — the surrounding
          bar (`legs-panel.tsx`) sets a light `--reference-dds-bar-foreground` for ITS OWN empty
          background, which the tab's light `bg-card` (matches the reference exactly, pixel-
          sampled) would otherwise inherit, reading as near-invisible light-on-light. `aria-
          selected` (the currently-open tab) gets a visibly distinct ring/background, not just a
          different chevron. */}
      <button
        type="button"
        role="tab"
        aria-selected={expanded}
        onClick={onToggle}
        className={`flex min-w-36 flex-col items-start gap-0.5 rounded-t-md border px-2.5 py-1.5 text-left text-xs text-card-foreground hover:bg-accent ${
          expanded ? 'border-primary bg-accent ring-2 ring-primary ring-inset' : 'border-border bg-card'
        }`}
      >
        <span className="font-semibold">{leg.service_name_ru}</span>
        <span className="flex items-center gap-1 text-muted-foreground">
          {leg.response_status_at_offset_ms !== null ? <span>{formatCallDurationMs(leg.response_status_at_offset_ms)}</span> : null}
          <span>{serviceResponseStatusLabelRu(leg.response_status)}</span>
          <span aria-hidden="true">{expanded ? '⌄' : '⌃'}</span>
        </span>
      </button>

      {expanded ? (
        <div
          className="absolute bottom-full left-0 z-10 mb-1 flex w-72 flex-col gap-2 rounded-lg border border-border bg-popover p-2 shadow-md"
          data-slot="dds-leg-popup"
        >
          <ul className="flex flex-col gap-1" data-slot="dds-leg-history">
            {leg.history.length === 0 ? (
              <li className="text-xs text-muted-foreground">{t('ddsLegHistoryEmpty')}</li>
            ) : (
              leg.history.map((entry) => (
                <li key={entry.event_id} className="text-xs">
                  <span className="font-medium">{entry.actor_display_ru}</span>{' '}
                  <span className="text-muted-foreground">{formatCallDurationMs(entry.at_offset_ms)}</span>{' '}
                  <span>{serviceResponseStatusLabelRu(entry.new_status)}</span>
                  {entry.order_number ? (
                    <span className="text-muted-foreground">
                      {' '}
                      · {t('ddsLegOrderNumberLabel')}: {entry.order_number}
                    </span>
                  ) : null}
                  {entry.comment_ru ? <span> · {entry.comment_ru}</span> : null}
                </li>
              ))
            )}
          </ul>

          {canEdit ? (
            editing ? (
              <div className="flex flex-col gap-1.5 border-t border-border pt-2" data-slot="dds-leg-form">
                <Label htmlFor={`dds-leg-${leg.assignment_id}-status`}>{t('ddsLegStatusLabel')}</Label>
                <select
                  id={`dds-leg-${leg.assignment_id}-status`}
                  className="h-7 w-full rounded-lg border border-input bg-transparent px-2 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  value={trigger}
                  disabled={pending}
                  onChange={(event) => setTrigger(event.target.value)}
                >
                  {leg.available_actions.map((action) => (
                    <option key={action.action_id} value={action.action_id}>
                      {action.label_ru}
                    </option>
                  ))}
                </select>
                <Label htmlFor={`dds-leg-${leg.assignment_id}-order`}>{t('ddsLegOrderNumberLabel')}</Label>
                <Input
                  id={`dds-leg-${leg.assignment_id}-order`}
                  className="h-7 text-xs"
                  value={orderNumber}
                  disabled={pending}
                  onChange={(event) => setOrderNumber(event.target.value)}
                />
                <Label htmlFor={`dds-leg-${leg.assignment_id}-comment`}>{t('ddsLegCommentLabel')}</Label>
                <Textarea
                  id={`dds-leg-${leg.assignment_id}-comment`}
                  className="min-h-14 text-xs"
                  value={comment}
                  disabled={pending}
                  onChange={(event) => setComment(event.target.value)}
                />
                {errorMessage ? (
                  <p role="alert" className="text-xs text-destructive">
                    {errorMessage}
                  </p>
                ) : null}
                <div className="flex justify-end gap-1">
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    aria-label={t('ddsLegFormConfirmButton')}
                    disabled={pending || trigger === ''}
                    onClick={() => void handleSubmit()}
                  >
                    ✓
                  </Button>
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    aria-label={t('ddsLegFormCancelButton')}
                    disabled={pending}
                    onClick={() => setEditing(false)}
                  >
                    ×
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex justify-end border-t border-border pt-2">
                <Button type="button" size="icon" variant="outline" aria-label={t('ddsLegEditButton')} onClick={openEditor}>
                  ✎
                </Button>
              </div>
            )
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
