// Call state panel (SPEC §15, §32; D9; R4) — the same `CallStateView` the phone widget consumes,
// read-only here (no barge-in/level-meter UI, only the instructor-relevant fields).
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { CallStateView } from '@/shared/api';
import { callPhaseLabelRu } from './instructor-labels';

interface CallStateSectionProps {
  callState: CallStateView;
}

export function CallStateSection({ callState }: CallStateSectionProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorCallStateTitle')}</h2>
        <Badge variant={callState.phase === 'CONNECTED' ? 'default' : 'outline'}>{callPhaseLabelRu(callState.phase)}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-sm">
        {callState.caller_display_ru ? (
          <p>
            {t('instructorCallStateCallerLabel')}: {callState.caller_display_ru}
          </p>
        ) : null}
        {callState.duration_ms !== null ? (
          <p className="text-xs text-muted-foreground">
            {t('instructorCallStateDurationLabel')}: {formatCallDurationMs(callState.duration_ms)}
          </p>
        ) : null}
        {callState.caller_speaking ? (
          <p className="text-xs text-muted-foreground" data-slot="caller-speaking">
            {t('instructorCallStateSpeakingLabel')}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
