// I7 E53 (G19, ТЗ ¶186 «Локализация на русском языке»): a scenario validation issue in Russian.
// The backend's §30.8 messages are English f-strings (`domain/scenario/validation.py`); the
// report carries the structured `rule_number`, so the Russian text is a template per rule number
// (`scenarioIssueR<n>` in ru.ts). A rule number without a template — one a later epic adds — keeps
// the server's English text, so nothing is ever hidden. The only WARNING the loader emits today
// (§30.6.4, a caller-belief change on an unobservable event) has its own template.
import { ru } from '@/shared/i18n/ru';
import type { ScenarioValidationReport } from '@/shared/api';

type ScenarioValidationIssue = ScenarioValidationReport['issues'][number];

const CALLER_BELIEF_WARNING = 'MUTATE_CALLER_BELIEF';

/** The issue's Russian text, or its English `message` when no template exists for it. */
export function scenarioIssueMessageRu(issue: ScenarioValidationIssue): string {
  if (issue.severity === 'WARNING') {
    return issue.message.includes(CALLER_BELIEF_WARNING) ? ru.scenarioIssueWarningCallerBelief : issue.message;
  }
  const key = `scenarioIssueR${issue.rule_number}`;
  return key in ru ? ru[key as keyof typeof ru] : issue.message;
}
