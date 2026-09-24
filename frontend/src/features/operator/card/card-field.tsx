// Dispatches one `CardFieldSpec` to the control its `control` (§70.5.2) names: `TOGGLE_SET` and
// `CHIPS` are the two multi-value (`STRING_LIST`) controls, everything else is the single-value
// `CardFieldControl`. The one place a group renderer needs to know about to add a field.
import type { CardFieldSpec, FactValue } from '@/entities/card';
import { CardFieldControl } from './field-control';
import { ToggleSetControl } from './toggle-set-control';
import { ChipsControl } from './chips-control';
import type { CommitCardField } from './use-card-field-commit';

interface CardFieldProps {
  spec: CardFieldSpec;
  confirmedValue: FactValue | undefined;
  disabled: boolean;
  onCommit: CommitCardField;
  /** The questionnaire's row layout (`field-group-section.tsx`) renders its own left-hand label
   * and passes this so the control does not repeat it. */
  hideLabel?: boolean;
}

export function CardField({ spec, confirmedValue, disabled, onCommit, hideLabel }: CardFieldProps) {
  if (spec.control === 'TOGGLE_SET') {
    return <ToggleSetControl spec={spec} confirmedValue={confirmedValue} disabled={disabled} onCommit={onCommit} hideLabel={hideLabel} />;
  }
  if (spec.control === 'CHIPS') {
    return <ChipsControl spec={spec} confirmedValue={confirmedValue} disabled={disabled} onCommit={onCommit} hideLabel={hideLabel} />;
  }
  return <CardFieldControl spec={spec} confirmedValue={confirmedValue} disabled={disabled} onCommit={onCommit} hideLabel={hideLabel} />;
}
