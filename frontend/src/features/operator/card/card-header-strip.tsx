// The reference card's header strip (ui-check D-3, `screenshot-card112/image1-2.png`): the three
// phone rows (АОН / предоставленный / телефон на место), the card's identity and the red
// `fill_within_ms` countdown (REQ-3010), and the «нет контакта» / «срыв звонка» / «Отказ от
// скорой» (`flags.ambulance_refused`) toggle row v2 defines. Only rendered for a v2 card — v1 has
// none of these `group: header`/`group: flags` fields, so `CardForm` never mounts this for v1.
import { useEffect, useState } from 'react';
import { t } from '@/shared/i18n';
import type { CardFieldSpec, OperatorCardView } from '@/entities/card';
import { formatCallDurationMs } from '@/entities/call';
import { CardFieldControl } from './field-control';
import type { CommitCardField } from './use-card-field-commit';
import { computeFillRemainingMs, useFillWithinMs } from './use-fill-deadline';
import { useDisplayNumber } from './use-display-number';

interface CardHeaderStripProps {
  sessionId: string;
  card: OperatorCardView;
  headerFields: readonly CardFieldSpec[];
  flagFields: readonly CardFieldSpec[];
  disabled: boolean;
  onCommit: CommitCardField;
  answeredAtOffsetMs: number | null;
  monotonicOffsetMs: number;
}

export function CardHeaderStrip({
  sessionId,
  card,
  headerFields,
  flagFields,
  disabled,
  onCommit,
  answeredAtOffsetMs,
  monotonicOffsetMs,
}: CardHeaderStripProps) {
  const fillWithinMs = useFillWithinMs(sessionId);
  const displayNumber = useDisplayNumber(sessionId);

  const [remainingMs, setRemainingMs] = useState(() => computeFillRemainingMs(answeredAtOffsetMs, monotonicOffsetMs, fillWithinMs));
  const [tracked, setTracked] = useState({ answeredAtOffsetMs, monotonicOffsetMs, fillWithinMs });
  if (tracked.answeredAtOffsetMs !== answeredAtOffsetMs || tracked.monotonicOffsetMs !== monotonicOffsetMs || tracked.fillWithinMs !== fillWithinMs) {
    setTracked({ answeredAtOffsetMs, monotonicOffsetMs, fillWithinMs });
    setRemainingMs(computeFillRemainingMs(answeredAtOffsetMs, monotonicOffsetMs, fillWithinMs));
  }

  useEffect(() => {
    if (answeredAtOffsetMs === null) return;
    const id = setInterval(() => setRemainingMs((previous) => (previous === null ? previous : previous - 1000)), 1000);
    return () => clearInterval(id);
  }, [answeredAtOffsetMs]);

  const overdue = remainingMs !== null && remainingMs <= 0;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3" data-slot="card-header-strip">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap gap-3">
          {headerFields.map((spec) => (
            <div key={spec.field_path} className="w-40">
              <CardFieldControl spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} />
            </div>
          ))}
        </div>
        {/* Manager review (I3 E3b): «Происшествие N» (the real `display_number`, never the card's
            UUID) as one line, the countdown as its own boxed element at the far right — the
            reference's shape (`screenshot-card112/image1.png`: id above, a separate dark timer
            box beside/below it). */}
        <div className="flex items-center gap-3">
          {displayNumber !== null ? (
            <span className="text-sm font-semibold" data-slot="card-number">
              {t('operatorCardNumberLabel')} {displayNumber}
            </span>
          ) : null}
          {remainingMs !== null ? (
            <span
              className={`rounded-md border border-border px-3 py-1.5 font-mono text-lg ${overdue ? 'border-destructive text-destructive' : ''}`}
              data-slot="card-fill-timer"
              data-overdue={overdue}
            >
              {formatCallDurationMs(Math.abs(remainingMs))}
            </span>
          ) : null}
        </div>
      </div>
      {flagFields.length > 0 ? (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('operatorGroupFlags')}>
          {flagFields.map((spec) => (
            <CardFieldControl key={spec.field_path} spec={spec} confirmedValue={card.values[spec.field_path]} disabled={disabled} onCommit={onCommit} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
