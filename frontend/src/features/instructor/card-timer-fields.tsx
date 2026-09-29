// I4 E31 / I7 E49 (Q-E31-2): the timer override fieldset — used by the lesson form (one per plan
// entry) and the single-session form (one for the whole session). Same three fields, same
// validation, same "empty keeps the scenario's value" placeholder as `card-timers.ts` defines.
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { Hint } from '@/shared/ui/tour';
import { TIMER_KEYS, timerSecondsValid, type TimerKey, type TimerSeconds } from './card-timers';

const TIMER_LABEL_KEY: Record<TimerKey, keyof typeof ru> = {
  accept_within_ms: 'lessonFormEntryAcceptTimerLabel',
  fill_within_ms: 'lessonFormEntryFillTimerLabel',
  not_completed_after_ms: 'lessonFormEntryNotCompletedTimerLabel',
};

interface CardTimerFieldsProps {
  /** A prefix for the controls' ids — several entries, or several forms, may be on one page. */
  idPrefix: string;
  timerSeconds: TimerSeconds;
  onChange: (timerSeconds: TimerSeconds) => void;
  /** `data-tour` target for the guided tour; omitted where no tour step points at it. */
  tourTarget?: string;
}

export function CardTimerFields({ idPrefix, timerSeconds, onChange, tourTarget }: CardTimerFieldsProps) {
  return (
    <fieldset className="flex flex-col gap-2" data-slot="card-timers" data-tour={tourTarget}>
      <legend className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {t('lessonFormEntryTimersLabel')}
        <Hint text={t('hintLessonTimers')} />
      </legend>
      {TIMER_KEYS.map((timerKey) => (
        <div key={timerKey} className="flex flex-col gap-1.5">
          <Label htmlFor={`${idPrefix}-timer-${timerKey}`}>{t(TIMER_LABEL_KEY[timerKey])}</Label>
          <Input
            id={`${idPrefix}-timer-${timerKey}`}
            type="number"
            min={1}
            placeholder={t('lessonFormEntryTimerPlaceholder')}
            value={timerSeconds[timerKey]}
            aria-invalid={!timerSecondsValid(timerSeconds[timerKey])}
            onChange={(event) => onChange({ ...timerSeconds, [timerKey]: event.target.value })}
          />
        </div>
      ))}
      <p className="text-xs text-muted-foreground">{t('lessonFormEntryTimersHint')}</p>
    </fieldset>
  );
}
