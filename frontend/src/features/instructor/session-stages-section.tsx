// Session + stages strip (SPEC §7, §13; D6, HLD §10.8/§10.10; R4). Shows the session's own state,
// which `RoleStage` is active and (while `state === 'ROLE_TRANSITION'`) a read-only countdown —
// this is the INSTRUCTOR console, so there is no `continueToNextStage` button here (R6: "only the
// next-stage holder or the instructor may continue" — the instructor continues from their OWN
// role's console per the operator/DDS hand-over screen, not from this read-only overview).
// Mirrors `features/operator/console-page.tsx`'s `useCountdownSeconds`, purely locally between
// server refreshes (DESIGN: no client clock authority beyond ticking a countdown between events;
// R1: the sim clock — and this countdown target — is frozen for the whole transition).
import { useEffect, useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { formatCallDurationMs } from '@/entities/call';
import type { RoleStageView, RoleType, SessionDetail } from '@/shared/api';
import { sessionStateLabelRu, stageStateLabelRu } from './instructor-labels';

const ROLE_TYPE_LABEL_KEY: Record<RoleType, keyof typeof ru> = {
  OPERATOR_112: 'roleTypeOperator112',
  DDS: 'roleTypeDds',
  EDDS: 'roleTypeEdds',
};

function computeRemainingSeconds(targetOffsetMs: number | null, nowOffsetMs: number): number {
  return targetOffsetMs === null ? 0 : Math.max(0, Math.ceil((targetOffsetMs - nowOffsetMs) / 1000));
}

function useCountdownSeconds(targetOffsetMs: number | null, nowOffsetMs: number): number {
  const [remaining, setRemaining] = useState(() => computeRemainingSeconds(targetOffsetMs, nowOffsetMs));
  const [trackedTarget, setTrackedTarget] = useState(targetOffsetMs);
  const [trackedNow, setTrackedNow] = useState(nowOffsetMs);
  if (trackedTarget !== targetOffsetMs || trackedNow !== nowOffsetMs) {
    setTrackedTarget(targetOffsetMs);
    setTrackedNow(nowOffsetMs);
    setRemaining(computeRemainingSeconds(targetOffsetMs, nowOffsetMs));
  }

  useEffect(() => {
    if (targetOffsetMs === null) return;
    const interval = setInterval(() => {
      setRemaining((previous) => Math.max(0, previous - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [targetOffsetMs, nowOffsetMs]);

  return remaining;
}

interface SessionStagesSectionProps {
  session: SessionDetail;
  stages: readonly RoleStageView[];
}

export function SessionStagesSection({ session, stages }: SessionStagesSectionProps) {
  const remainingSeconds = useCountdownSeconds(session.transition_continue_available_at_offset_ms, session.monotonic_offset_ms);
  const activeStage = stages.find((stage) => stage.role_stage_id === session.active_role_stage_id) ?? null;
  const participantNameByUserId = new Map(session.participants.map((participant) => [participant.user_id, participant.display_name_ru]));

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorOverviewSessionTitle')}</h2>
        <Badge variant="outline" data-slot="session-state-badge">
          {t('sessionsStateLabel')}: {sessionStateLabelRu(session.state)}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm">
          {t('instructorOverviewActiveRoleLabel')}:{' '}
          {activeStage ? t(ROLE_TYPE_LABEL_KEY[activeStage.role_type]) : t('instructorOverviewNoActiveRole')}
        </p>
        {session.state === 'ROLE_TRANSITION' ? (
          <p className="text-sm text-muted-foreground" data-slot="transition-countdown">
            {remainingSeconds > 0
              ? `${t('operatorRoleTransitionCountdownLabel')}: ${remainingSeconds}`
              : t('operatorRoleTransitionReady')}
          </p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {stages.map((stage) => (
            <li key={stage.role_stage_id} className="flex flex-col gap-1 rounded-md border border-border p-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{t(ROLE_TYPE_LABEL_KEY[stage.role_type])}</span>
                <Badge variant={stage.role_stage_id === session.active_role_stage_id ? 'default' : 'outline'}>
                  {stageStateLabelRu(stage.role_type, stage.state)}
                </Badge>
              </div>
              <span className="text-muted-foreground">
                {t('instructorOverviewStageParticipantLabel')}:{' '}
                {stage.participant_user_id
                  ? (participantNameByUserId.get(stage.participant_user_id) ?? stage.participant_user_id)
                  : t('instructorOverviewStageNoParticipant')}
              </span>
              {stage.started_at_offset_ms !== null ? (
                <span className="text-muted-foreground">
                  {t('instructorOverviewStageStartedLabel')}: {formatCallDurationMs(stage.started_at_offset_ms)}
                </span>
              ) : null}
              {stage.completed_at_offset_ms !== null ? (
                <span className="text-muted-foreground">
                  {t('instructorOverviewStageCompletedLabel')}: {formatCallDurationMs(stage.completed_at_offset_ms)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
