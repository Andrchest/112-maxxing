// The operator card form (SPEC §9: "the trainee manually edits the incident card"; D12 design
// decision #2). Rendered entirely from the server's `CardFieldSpec[]` — labels, groups, value
// types are never retyped here. One `setCardField` command per field commit (blur / Enter /
// select change), a fresh `client_command_id` per command, no request when the value did not
// change, and a failed command restores the last server-confirmed value. Nothing but the
// trainee's own edit ever reaches `onCommit`: this component does not read the transcript or the
// session-events store at all (DESIGN 2's structural guarantee — there is no data path from
// ASR_FINAL into a card field here to begin with).
import { useState } from 'react';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useCardStore, groupCardFields, type CardFieldSpec, type FactValue } from '@/entities/card';
import { useStageStore, hasAvailableAction } from '@/entities/stage';
import { setCardField, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

type CommitResult = { ok: true } | { ok: false; message: string };

const GROUP_LABEL_KEY: Record<string, keyof typeof ru> = {
  incident: 'operatorGroupIncident',
  address: 'operatorGroupAddress',
  caller: 'operatorGroupCaller',
  description: 'operatorGroupDescription',
  people: 'operatorGroupPeople',
  hazards: 'operatorGroupHazards',
  flags: 'operatorGroupFlags',
  notes: 'operatorGroupNotes',
  recipients: 'operatorGroupRecipients',
};

function groupLabel(key: string): string {
  return t(GROUP_LABEL_KEY[key] ?? 'operatorGroupOther');
}

const INCIDENT_TYPE_LABEL_KEY: Record<string, keyof typeof ru> = {
  FIRE: 'incidentTypeFire',
  MEDICAL: 'incidentTypeMedical',
  CRIME: 'incidentTypeCrime',
  TRAFFIC_ACCIDENT: 'incidentTypeTrafficAccident',
  GAS_LEAK: 'incidentTypeGasLeak',
  UTILITY_FAILURE: 'incidentTypeUtilityFailure',
  RESCUE: 'incidentTypeRescue',
  OTHER: 'incidentTypeOther',
};

const CALLER_RELATIONSHIP_LABEL_KEY: Record<string, keyof typeof ru> = {
  VICTIM: 'callerRelationshipVictim',
  WITNESS: 'callerRelationshipWitness',
  NEIGHBOUR: 'callerRelationshipNeighbour',
  RELATIVE: 'callerRelationshipRelative',
  PASSERBY: 'callerRelationshipPasserby',
  OFFICIAL: 'callerRelationshipOfficial',
  UNKNOWN: 'callerRelationshipUnknown',
};

// `CardFieldSpec.enum_name` names which enum backs an ENUM field; this is the (small, structural)
// lookup from enum member -> Russian label for the two enums SPEC §9's field list actually uses
// (`10-domain-model.md` §10.6). Neither `CardFieldSpec` nor any other schema in `openapi.yaml`
// carries a per-option label, so this is the frontend's own presentation concern, not a retyping
// of the field list itself (see the report's HLD gaps).
const ENUM_LABEL_KEYS_BY_ENUM_NAME: Record<string, Record<string, keyof typeof ru>> = {
  IncidentType: INCIDENT_TYPE_LABEL_KEY,
  CallerRelationship: CALLER_RELATIONSHIP_LABEL_KEY,
};

function toDraftString(spec: CardFieldSpec, value: FactValue | undefined): string {
  if (spec.value_type === 'BOOLEAN') {
    return value === true ? 'true' : 'false';
  }
  if (value === undefined || value === null) {
    return '';
  }
  return String(value);
}

function fromDraftString(spec: CardFieldSpec, draft: string): FactValue {
  switch (spec.value_type) {
    case 'BOOLEAN':
      return draft === 'true';
    case 'INTEGER': {
      if (draft.trim() === '') return null;
      const parsed = Number(draft);
      return Number.isNaN(parsed) ? null : Math.trunc(parsed);
    }
    case 'FLOAT': {
      if (draft.trim() === '') return null;
      const parsed = Number(draft);
      return Number.isNaN(parsed) ? null : parsed;
    }
    default:
      return draft;
  }
}

interface CardFieldRowProps {
  spec: CardFieldSpec;
  confirmedValue: FactValue | undefined;
  disabled: boolean;
  onCommit: (spec: CardFieldSpec, value: FactValue) => Promise<CommitResult>;
}

function CardFieldRow({ spec, confirmedValue, disabled, onCommit }: CardFieldRowProps) {
  const confirmedDraft = toDraftString(spec, confirmedValue);
  const [draft, setDraft] = useState(confirmedDraft);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // Adjust state during render instead of in an effect (React docs: "Adjusting state when a
  // prop changes") — a new server-confirmed value (a command response, or an idempotent
  // CARD_FIELD_CHANGED fold, D12 design decision #5) resets the draft in the same render, not a
  // render-after-next.
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
  const enumLabelKeys = spec.value_type === 'ENUM' && spec.enum_name ? ENUM_LABEL_KEYS_BY_ENUM_NAME[spec.enum_name] : undefined;

  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={inputId}>{spec.label_ru}</Label>
      {spec.value_type === 'BOOLEAN' ? (
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
      ) : enumLabelKeys ? (
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
          {Object.entries(enumLabelKeys).map(([value, labelKey]) => (
            <option key={value} value={value}>
              {t(labelKey)}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={inputId}
          type={spec.value_type === 'INTEGER' || spec.value_type === 'FLOAT' ? 'number' : 'text'}
          value={draft}
          disabled={disabled || pending}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commit(draft)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.currentTarget.blur();
            }
          }}
        />
      )}
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface CardFormProps {
  sessionId: string;
}

export function CardForm({ sessionId }: CardFormProps) {
  const card = useCardStore((state) => state.card);
  const availableActions = useStageStore((state) => state.availableActions);
  const canEdit = hasAvailableAction(availableActions, 'edit_card');

  async function handleCommit(spec: CardFieldSpec, newValue: FactValue): Promise<CommitResult> {
    try {
      const response = await setCardField(sessionId, {
        field_path: spec.field_path,
        new_value: newValue,
        client_command_id: crypto.randomUUID(),
      });
      useCardStore.getState().setCard(response.card);
      return { ok: true };
    } catch (error) {
      const message = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
      return { ok: false, message };
    }
  }

  if (!card) {
    return null;
  }

  // `recipients.services` is edited only through the services panel (SPEC §9, `setCardField`'s
  // own contract) — excluded here so it is never rendered (and never committed) twice.
  const groups = groupCardFields(card.field_specs.filter((spec) => spec.field_path !== 'recipients.services'));

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorCardTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map((group) => (
          <div key={group.key} className="flex flex-col gap-2">
            <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{groupLabel(group.key)}</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {group.fields.map((spec) => (
                <CardFieldRow
                  key={spec.field_path}
                  spec={spec}
                  confirmedValue={card.values[spec.field_path]}
                  disabled={!canEdit}
                  onCommit={handleCommit}
                />
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
