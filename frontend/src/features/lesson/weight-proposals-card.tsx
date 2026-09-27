// I3 E9a (70 §70.3.7, F-15 «…искусственный интеллект… должен предложить преподавателю… стоить
// десять баллов… или пять… или шесть»): the instructor asks for a weight per card, reads each
// proposal beside the card's current weight and its reason, ticks the ones to take and accepts
// them. The server stores proposals and applies nothing until `acceptWeightProposals`; this card
// never computes a weight, it only shows the server's numbers (scoring stays deterministic, D11).
// I5 E39: read-only (controls disabled, with the ownership hint) for an instructor who did not
// create the lesson.
import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import {
  acceptWeightProposals,
  getWeightProposals,
  problemMessageRu,
  queryKeys,
  requestWeightProposals,
  type ProblemCode,
  type WeightProposalSet,
} from '@/shared/api';

const FALLBACK_REASON_KEY: Record<string, keyof typeof ru> = {
  LLM_TIMEOUT: 'weightProposalsFallbackLlmTimeout',
  LLM_UNAVAILABLE: 'weightProposalsFallbackLlmUnavailable',
  LLM_INVALID_OUTPUT: 'weightProposalsFallbackLlmInvalidOutput',
};

function sourceLine(set: WeightProposalSet): string {
  if (set.source === 'LLM') {
    return set.model_name ? `${t('weightProposalsSourceLlm')} (${set.model_name})` : t('weightProposalsSourceLlm');
  }
  const reasonKey = set.fallback_reason ? FALLBACK_REASON_KEY[set.fallback_reason] : undefined;
  return reasonKey
    ? `${t('weightProposalsSourceHeuristic')} — ${t('weightProposalsFallbackPrefix')}: ${t(reasonKey)}`
    : t('weightProposalsSourceHeuristic');
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

interface WeightProposalsCardProps {
  lessonId: string;
  /** The plan entry's scenario title (and difficulty) for a position — rendered by the page. */
  renderCardLabel: (position: number, scenarioVersionId: string) => ReactNode;
  onWeightsChanged?: () => void;
  /** I5 E39: the caller may change this lesson (its creator or an ADMIN). */
  canChange?: boolean;
}

export function WeightProposalsCard({ lessonId, renderCardLabel, onWeightsChanged, canChange = true }: WeightProposalsCardProps) {
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  const proposalsQuery = useQuery({
    queryKey: queryKeys.weightProposals.detail(lessonId),
    queryFn: async () => {
      try {
        return await getWeightProposals(lessonId);
      } catch (error) {
        if (error instanceof ProblemError && error.code === 'NOT_FOUND') return null;
        throw error;
      }
    },
    retry: false,
  });

  function store(set: WeightProposalSet) {
    queryClient.setQueryData(queryKeys.weightProposals.detail(lessonId), set);
  }

  const requestMutation = useMutation({
    mutationFn: () => requestWeightProposals(lessonId),
    onSuccess: (set) => {
      store(set);
      setChosen(new Set()); // nothing is ticked for the instructor: accepting is their choice
    },
  });

  const acceptMutation = useMutation({
    mutationFn: (positions: number[]) => acceptWeightProposals(lessonId, positions),
    onSuccess: (set) => {
      store(set);
      setChosen(new Set());
      void queryClient.invalidateQueries({ queryKey: queryKeys.lessons.detail(lessonId), exact: true });
      void queryClient.invalidateQueries({ queryKey: queryKeys.lessons.report(lessonId) });
      onWeightsChanged?.();
    },
  });

  function toggle(position: number) {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(position)) next.delete(position);
      else next.add(position);
      return next;
    });
  }

  const set = proposalsQuery.data ?? null;

  return (
    <Card className="max-w-2xl" data-slot="weight-proposals">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('weightProposalsTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">{t('weightProposalsIntro')}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => requestMutation.mutate()}
            disabled={requestMutation.isPending || !canChange}
          >
            {requestMutation.isPending ? t('weightProposalsRequesting') : t('weightProposalsRequestButton')}
          </Button>
        </div>
        {!canChange ? (
          <p className="text-xs text-muted-foreground" data-slot="ownership-hint">
            {t('ownershipHintLesson')}
          </p>
        ) : null}
        {requestMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(requestMutation.error)}
          </p>
        ) : null}
        {proposalsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(proposalsQuery.error)}
          </p>
        ) : null}
        {proposalsQuery.isSuccess && set === null ? (
          <p className="text-sm text-muted-foreground">{t('weightProposalsEmpty')}</p>
        ) : null}
        {set ? (
          <>
            <p className="text-xs text-muted-foreground" data-slot="weight-proposals-source">
              {sourceLine(set)}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="p-2 font-medium">{t('weightProposalsColumnCard')}</th>
                    <th className="p-2 font-medium">{t('weightProposalsColumnCurrent')}</th>
                    <th className="p-2 font-medium">{t('weightProposalsColumnProposed')}</th>
                    <th className="p-2 font-medium">{t('weightProposalsColumnReason')}</th>
                    <th className="p-2 font-medium">{t('weightProposalsColumnAccept')}</th>
                  </tr>
                </thead>
                <tbody>
                  {set.proposals.map((line) => (
                    <tr key={line.position} className="border-b border-border/60 align-top" data-slot="weight-proposal-row">
                      <td className="p-2">{renderCardLabel(line.position, line.scenario_version_id)}</td>
                      <td className="p-2 font-mono" data-slot="current-weight">
                        {line.current_weight}
                      </td>
                      <td className="p-2 font-mono font-medium" data-slot="proposed-weight">
                        {line.proposed_weight}
                      </td>
                      <td className="p-2 text-xs">{line.reason_ru}</td>
                      <td className="p-2 text-center">
                        {line.accepted_at ? (
                          <span className="text-xs text-muted-foreground">{t('weightProposalsAccepted')}</span>
                        ) : (
                          <input
                            type="checkbox"
                            className="size-4 accent-primary"
                            aria-label={`${t('weightProposalsColumnAccept')} ${line.position}`}
                            checked={chosen.has(line.position)}
                            disabled={!canChange}
                            onChange={() => toggle(line.position)}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => acceptMutation.mutate([...chosen].sort((a, b) => a - b))}
                disabled={chosen.size === 0 || acceptMutation.isPending || !canChange}
              >
                {acceptMutation.isPending ? t('weightProposalsAccepting') : t('weightProposalsAcceptButton')}
              </Button>
            </div>
            {acceptMutation.error ? (
              <p role="alert" className="text-sm text-destructive">
                {problemText(acceptMutation.error)}
              </p>
            ) : null}
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
