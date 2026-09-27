// I5 E38 (Q-E9b-3 variant г): the three «сдал / не сдал» controls — a threshold of score percent,
// a limit of failed rules, «a critical error fails» — each switched on or off by its own box
// (`pass-criteria.ts` holds the draft, its validation and the request field). Used by the
// single-session form and the lesson form; the lesson's criteria apply to every card.
import { Input } from '@/shared/ui/input';
import { t } from '@/shared/i18n';
import { maxFailedValid, minScoreValid, passCriteriaProblem, type PassCriteriaDraft } from './pass-criteria';

interface PassCriteriaFieldsProps {
  /** A prefix for the controls' ids — two forms may be on one page. */
  idPrefix: string;
  draft: PassCriteriaDraft;
  onChange: (draft: PassCriteriaDraft) => void;
}

export function PassCriteriaFields({ idPrefix, draft, onChange }: PassCriteriaFieldsProps) {
  const problem = passCriteriaProblem(draft);
  return (
    <fieldset className="flex flex-col gap-2" data-slot="pass-criteria">
      <legend className="text-sm font-medium">{t('passCriteriaTitle')}</legend>
      <div className="flex items-center gap-2">
        <input
          id={`${idPrefix}-pass-min-score-on`}
          type="checkbox"
          className="size-4 accent-primary"
          checked={draft.minScoreOn}
          onChange={(event) => onChange({ ...draft, minScoreOn: event.target.checked })}
        />
        <label htmlFor={`${idPrefix}-pass-min-score-on`} className="text-sm">
          {t('passCriteriaMinScoreLabel')}
        </label>
        <Input
          id={`${idPrefix}-pass-min-score`}
          className="w-20"
          inputMode="numeric"
          aria-label={t('passCriteriaMinScoreLabel')}
          value={draft.minScore}
          disabled={!draft.minScoreOn}
          aria-invalid={!minScoreValid(draft)}
          onChange={(event) => onChange({ ...draft, minScore: event.target.value })}
        />
        <span className="text-sm text-muted-foreground">%</span>
      </div>
      <div className="flex items-center gap-2">
        <input
          id={`${idPrefix}-pass-max-failed-on`}
          type="checkbox"
          className="size-4 accent-primary"
          checked={draft.maxFailedOn}
          onChange={(event) => onChange({ ...draft, maxFailedOn: event.target.checked })}
        />
        <label htmlFor={`${idPrefix}-pass-max-failed-on`} className="text-sm">
          {t('passCriteriaMaxFailedRulesLabel')}
        </label>
        <Input
          id={`${idPrefix}-pass-max-failed`}
          className="w-20"
          inputMode="numeric"
          aria-label={t('passCriteriaMaxFailedRulesLabel')}
          value={draft.maxFailed}
          disabled={!draft.maxFailedOn}
          aria-invalid={!maxFailedValid(draft)}
          onChange={(event) => onChange({ ...draft, maxFailed: event.target.value })}
        />
      </div>
      <div className="flex items-center gap-2">
        <input
          id={`${idPrefix}-pass-fail-on-critical`}
          type="checkbox"
          className="size-4 accent-primary"
          checked={draft.failOnCritical}
          onChange={(event) => onChange({ ...draft, failOnCritical: event.target.checked })}
        />
        <label htmlFor={`${idPrefix}-pass-fail-on-critical`} className="text-sm">
          {t('passCriteriaFailOnCriticalLabel')}
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{t('passCriteriaHint')}</p>
      {problem ? (
        <p role="alert" className="text-xs text-destructive" data-slot="pass-criteria-problem">
          {problem === 'NONE_ENABLED' ? t('passCriteriaNoneEnabled') : t('passCriteriaInvalidValue')}
        </p>
      ) : null}
    </fieldset>
  );
}
