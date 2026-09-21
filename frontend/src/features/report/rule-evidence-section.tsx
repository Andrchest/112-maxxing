// §29 item 14: evidence for every scoring rule. Renders `score_report.results` (not just the
// critical subset `CriticalErrorsSection` shows) — every rule row expands to its evidence list.
// An evidence item with `seq_no` set scrolls to / highlights that timeline entry via
// `onJumpToEvent`, owned by the parent (`report-page.tsx`) so this component never touches
// `TimelineSection`'s internals directly.
import { useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { ScoreResultView } from '@/shared/api';

interface RuleEvidenceSectionProps {
  results: readonly ScoreResultView[];
  onJumpToEvent?: (seqNo: number) => void;
}

export function RuleEvidenceSection({ results, onJumpToEvent }: RuleEvidenceSectionProps) {
  const [expandedRuleIds, setExpandedRuleIds] = useState<ReadonlySet<string>>(new Set());

  function toggle(ruleId: string): void {
    setExpandedRuleIds((previous) => {
      const next = new Set(previous);
      if (next.has(ruleId)) {
        next.delete(ruleId);
      } else {
        next.add(ruleId);
      }
      return next;
    });
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportEvidenceTitle')}</h2>
      </CardHeader>
      <CardContent>
        {results.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportEvidenceEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {results.map((result) => {
              const expanded = expandedRuleIds.has(result.rule_id);
              return (
                <li key={result.rule_id} className="flex flex-col gap-1.5 rounded-md border border-border p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{result.name_ru}</span>
                      {result.critical_failure ? <Badge variant="destructive">{t('reportEvidenceCriticalBadge')}</Badge> : null}
                      <Badge variant={result.passed ? 'default' : 'outline'}>{result.passed ? t('reportEvidencePassedYes') : t('reportEvidencePassedNo')}</Badge>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-muted-foreground">
                        {t('reportEvidencePointsLabel')}: {result.points_awarded} / {result.max_points}
                      </span>
                      <Button type="button" variant="ghost" size="xs" onClick={() => toggle(result.rule_id)}>
                        {expanded ? t('reportEvidenceCollapseButton') : t('reportEvidenceExpandButton')}
                      </Button>
                    </div>
                  </div>
                  {expanded ? (
                    <ul className="flex flex-col gap-1 border-t border-border pt-1.5">
                      {result.evidence.map((evidence, index) => (
                        <li key={index} className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span>{evidence.note_ru}</span>
                          {evidence.seq_no !== null && onJumpToEvent ? (
                            <Button type="button" variant="ghost" size="xs" onClick={() => onJumpToEvent(evidence.seq_no as number)}>
                              {t('reportEvidenceJumpToEventButton')}
                            </Button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
