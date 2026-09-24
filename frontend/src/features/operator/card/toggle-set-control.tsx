// The `TOGGLE_SET` control (§70.5.2): a `STRING_LIST` field whose `options` render as a row of
// blue toggle tags (the reference's questionnaire rows — «Где», «Признак пожара», «Угроза людям»,
// …). Clicking a tag commits the whole new list as one `setCardField` (D12 design decision #2: one
// command per edit — a toggle click is the trainee's one edit here, exactly like a text field's
// blur). Options with `routing: 'none'` are ordinary toggles too; nothing here treats a negative
// answer option as exclusive with its positive sibling — the schema declares no such constraint
// (§70.5.2).
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Label } from '@/shared/ui/label';
import type { CardFieldSpec, FactValue } from '@/entities/card';
import type { CommitCardField } from './use-card-field-commit';

interface ToggleSetControlProps {
  spec: CardFieldSpec;
  confirmedValue: FactValue | undefined;
  disabled: boolean;
  onCommit: CommitCardField;
  /** The questionnaire's row layout (`field-group-section.tsx`'s "row" variant) renders the row's
   * own left-hand label, so this stops the control repeating it under the tag row. */
  hideLabel?: boolean;
}

export function ToggleSetControl({ spec, confirmedValue, disabled, onCommit, hideLabel }: ToggleSetControlProps) {
  const confirmed = Array.isArray(confirmedValue) ? (confirmedValue as string[]) : [];
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(code: string): Promise<void> {
    const next = confirmed.includes(code) ? confirmed.filter((item) => item !== code) : [...confirmed, code];
    setPending(true);
    setError(null);
    const result = await onCommit(spec, next);
    setPending(false);
    if (!result.ok) {
      setError(result.message);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {hideLabel ? null : <Label>{spec.label_ru}</Label>}
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={spec.label_ru}>
        {(spec.options ?? []).map((option) => {
          const selected = confirmed.includes(option.code);
          return (
            <Button
              key={option.code}
              type="button"
              size="sm"
              variant={selected ? 'default' : 'outline'}
              aria-pressed={selected}
              disabled={disabled || pending}
              onClick={() => void toggle(option.code)}
            >
              {option.label_ru}
            </Button>
          );
        })}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
