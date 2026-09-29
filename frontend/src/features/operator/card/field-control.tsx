// One single-value card field, rendered by its `CardFieldSpec.control` (§70.5.2): TEXT, TEXTAREA,
// NUMBER, PHONE (all plain inputs), SELECT (v2 `options` or, absent those, the v1 `enum_name`
// table) and CHECKBOX (BOOLEAN). Multi-value controls (`TOGGLE_SET`, `CHIPS`) live in
// `toggle-set-control.tsx` / `chips-control.tsx` — a `STRING_LIST` value never reaches this
// component. Every commit is exactly one `setCardField` call through `onCommit` (D12 design
// decision #2); nothing here derives a value the trainee did not type or pick.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import type { CardFieldSpec, FactValue } from '@/entities/card';
import { fromDraftString, toDraftString } from './value-codec';
import { ENUM_LABEL_KEYS_BY_ENUM_NAME } from './enum-labels';
import type { CommitCardField } from './use-card-field-commit';

interface CardFieldControlProps {
  spec: CardFieldSpec;
  confirmedValue: FactValue | undefined;
  disabled: boolean;
  onCommit: CommitCardField;
  /** Hides the field's own `<Label>` — the header strip renders its own compact labels around a
   * `PHONE` control instead of the generic block layout. */
  hideLabel?: boolean;
}

export function CardFieldControl({ spec, confirmedValue, disabled, onCommit, hideLabel }: CardFieldControlProps) {
  const confirmedDraft = toDraftString(spec, confirmedValue);
  const [draft, setDraft] = useState(confirmedDraft);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Adjust state during render instead of in an effect (React docs: "Adjusting state when a
  // prop changes") — a new server-confirmed value (a command response, or an idempotent
  // CARD_FIELD_CHANGED fold, D12 design decision #5) resets the draft in the same render.
  const [renderedConfirmedDraft, setRenderedConfirmedDraft] = useState(confirmedDraft);
  if (confirmedDraft !== renderedConfirmedDraft) {
    setRenderedConfirmedDraft(confirmedDraft);
    setDraft(confirmedDraft);
  }

  async function commit(nextDraft: string): Promise<void> {
    if (nextDraft === confirmedDraft) {
      // DESIGN 2: no request on an unchanged value.
      return;
    }
    setPending(true);
    setError(null);
    const result = await onCommit(spec, fromDraftString(spec, nextDraft));
    setPending(false);
    if (!result.ok) {
      setDraft(confirmedDraft);
      setError(result.message);
    }
  }

  const inputId = `card-field-${spec.field_path}`;
  const control = spec.control ?? (spec.value_type === 'BOOLEAN' ? 'CHECKBOX' : spec.value_type === 'ENUM' ? 'SELECT' : 'TEXT');
  const selectOptions = spec.value_type === 'ENUM' ? spec.options : undefined;
  const enumLabelKeys = spec.value_type === 'ENUM' && !selectOptions && spec.enum_name ? ENUM_LABEL_KEYS_BY_ENUM_NAME[spec.enum_name] : undefined;

  let field: React.ReactNode;
  // Every `flags`-group `BOOLEAN` renders as the reference's toggle button (gsi image1's header
  // row: «Пострадавшие», «Нет на месте…», «Нет доступа…», «нет контакта», «срыв звонка» are all
  // buttons, not checkboxes) — whether or not the field carries the one-option `CardOption` a
  // routing-relevant flag does (`casualties`/`ambulance_refused`/`blocked` do; `no_contact`/
  // `call_dropped` do not, §70.5.2's routing binding never needed one for them). A v1 `BOOLEAN`
  // (`group: null`) and a v2 non-flag `BOOLEAN` (`caller.foreign`, `caller.foreign_language`) keep
  // the plain checkbox — the reference shows those as icons/checkboxes, not buttons.
  const isFlagToggle = control === 'CHECKBOX' && ((spec.options && spec.options.length === 1) || spec.group === 'flags');
  if (isFlagToggle) {
    const checked = draft === 'true';
    field = (
      <Button
        id={inputId}
        type="button"
        size="sm"
        variant={checked ? 'default' : 'outline'}
        aria-pressed={checked}
        disabled={disabled || pending}
        onClick={() => {
          const next = String(!checked);
          setDraft(next);
          void commit(next);
        }}
      >
        {spec.options?.[0]?.label_ru ?? spec.label_ru}
      </Button>
    );
  } else if (control === 'CHECKBOX') {
    field = (
      <input
        id={inputId}
        type="checkbox"
        className="size-4"
        checked={draft === 'true'}
        disabled={disabled || pending}
        onChange={(event) => {
          const next = String(event.target.checked);
          setDraft(next);
          void commit(next);
        }}
      />
    );
  } else if (control === 'SELECT') {
    field = (
      <select
        id={inputId}
        className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        value={draft}
        disabled={disabled || pending}
        onChange={(event) => {
          const next = event.target.value;
          setDraft(next);
          void commit(next);
        }}
      >
        <option value=""></option>
        {selectOptions
          ? selectOptions.map((option) => (
              <option key={option.code} value={option.code}>
                {option.label_ru}
              </option>
            ))
          : Object.entries(enumLabelKeys ?? {}).map(([value, labelKey]) => (
              <option key={value} value={value}>
                {t(labelKey)}
              </option>
            ))}
      </select>
    );
  } else if (control === 'TEXTAREA') {
    // I7 E55: a `max_length` (the reference's «0 / 1999» under «Описание со слов заявителя») caps
    // the input and shows the reference's own counter at the bottom right.
    const maxLength = spec.max_length ?? undefined;
    field = (
      <>
        <textarea
          id={inputId}
          className="min-h-20 w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
          value={draft}
          maxLength={maxLength}
          disabled={disabled || pending}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commit(draft)}
        />
        {maxLength !== undefined ? (
          <span className="self-end text-xs text-muted-foreground" data-slot="card-field-counter">
            {draft.length} / {maxLength}
          </span>
        ) : null}
      </>
    );
  } else {
    // TEXT, NUMBER, PHONE — a masked phone input is E7a's look; the value itself is free text.
    field = (
      <Input
        id={inputId}
        type={control === 'NUMBER' ? 'number' : 'text'}
        value={draft}
        maxLength={spec.max_length ?? undefined}
        disabled={disabled || pending}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void commit(draft)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.currentTarget.blur();
          }
        }}
      />
    );
  }

  // A toggle button already carries its own label text, so the block label above it would just
  // repeat it (the reference shows one line, not two, per flag).
  return (
    <div className="flex flex-col gap-1">
      {hideLabel || isFlagToggle ? null : <Label htmlFor={inputId}>{spec.label_ru}</Label>}
      {field}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
