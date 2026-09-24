// The `CHIPS` control (§70.5.2): a `STRING_LIST` field whose `options` render as a full-width
// search entry (the reference's «Что случилось?» picker, gsi image1/5/7 — «Введите тип
// происшествия» / «добавить тип происшествия») with the selected values as removable chips BELOW
// it (image2: chips «Происшествие 101», «П: Взрыв» under the input, not beside it). Generic over
// any `CHIPS` field with `options` — `recipients.services` never reaches this component (the
// services panel, I3 E2b′, owns that field's own picker and commands).
//
// Every add/remove is one `setCardField` command carrying the whole new list (D12 design decision
// #2 — one command per edit, the same discipline `ToggleSetControl` uses).
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { CardFieldSpec, CardOption, FactValue } from '@/entities/card';
import type { CommitCardField } from './use-card-field-commit';

interface ChipsControlProps {
  spec: CardFieldSpec;
  confirmedValue: FactValue | undefined;
  disabled: boolean;
  onCommit: CommitCardField;
  /** The row-layout questionnaire groups render their own left-hand label (`field-group-section`'s
   * "row" variant) — this stops the control from repeating it (only `incident.types` uses it, and
   * that field always keeps its own label; kept for the same shape as the other controls). */
  hideLabel?: boolean;
}

// `incident.types`' three questionnaire-backed codes get the reference's own chip wording — the
// same text `group-labels.ts` already uses for those groups' section titles («Происшествие 101» /
// «Происшествие 104» / «П: Взрыв», ui-check D-5) — rather than the option's bare numeral label
// («101»). Every other code (no reference evidence for its exact chip wording) keeps its own
// `label_ru`.
const CHIP_LABEL_OVERRIDE: Record<string, keyof typeof ru> = {
  '1': 'operatorGroupQFire',
  '13': 'operatorGroupQGas',
  '3': 'operatorGroupQExplosion',
};

function chipLabel(option: CardOption): string {
  const key = CHIP_LABEL_OVERRIDE[option.code];
  return key ? t(key) : option.label_ru;
}

export function ChipsControl({ spec, confirmedValue, disabled, onCommit, hideLabel }: ChipsControlProps) {
  const confirmed = Array.isArray(confirmedValue) ? (confirmedValue as string[]) : [];
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const options = spec.options ?? [];
  const selectedOptions = options.filter((option) => confirmed.includes(option.code));
  const needle = search.trim().toLocaleLowerCase('ru');
  const open = needle !== '';
  const choices = options.filter((option) => !confirmed.includes(option.code) && option.label_ru.toLocaleLowerCase('ru').includes(needle));

  async function apply(next: string[]): Promise<void> {
    setPending(true);
    setError(null);
    const result = await onCommit(spec, next);
    setPending(false);
    if (!result.ok) {
      setError(result.message);
    }
  }

  async function add(code: string): Promise<void> {
    setSearch('');
    await apply([...confirmed, code]);
  }

  async function remove(code: string): Promise<void> {
    await apply(confirmed.filter((item) => item !== code));
  }

  const inputId = `card-field-${spec.field_path}`;

  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label={spec.label_ru}>
      {hideLabel ? null : <Label htmlFor={inputId}>{spec.label_ru}</Label>}
      <div className="relative">
        <Input
          id={inputId}
          type="search"
          value={search}
          placeholder={t('operatorCardAddIncidentType')}
          disabled={disabled || pending}
          onChange={(event) => setSearch(event.target.value)}
        />
        {open ? (
          <ul className="absolute z-10 mt-1 flex max-h-48 w-full flex-col gap-0.5 overflow-y-auto rounded-lg border border-border bg-popover p-1 shadow-sm">
            {choices.map((option) => (
              <li key={option.code}>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  disabled={disabled || pending}
                  onClick={() => void add(option.code)}
                >
                  {option.label_ru}
                </Button>
              </li>
            ))}
            {choices.length === 0 ? <li className="px-2 py-1 text-xs text-muted-foreground">{t('operatorServicesPickerNothingFound')}</li> : null}
          </ul>
        ) : null}
      </div>
      {selectedOptions.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {selectedOptions.map((option) => (
            <Button
              key={option.code}
              type="button"
              size="sm"
              variant="default"
              disabled={disabled || pending}
              aria-label={`${t('operatorCardChipRemove')}: ${chipLabel(option)}`}
              onClick={() => void remove(option.code)}
            >
              {chipLabel(option)} ×
            </Button>
          ))}
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
