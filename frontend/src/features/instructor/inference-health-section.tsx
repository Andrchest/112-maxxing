// Inference health panel (SPEC §37; D8; R4) — `InstructorSessionOverview.inference_health`, the
// same `HealthReadyResponse` the header readiness badge already summarizes (`AppShell`'s
// `readiness` prop), spelled out here with the required-component list and model profile.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { HealthReadyResponse, HealthStatus } from '@/shared/api';

const READINESS_LABEL_KEY: Record<HealthStatus, keyof typeof ru> = {
  READY: 'readinessReady',
  WARMING: 'readinessWarming',
  NOT_READY: 'readinessNotReady',
  FATAL: 'readinessFatal',
};

const READINESS_BADGE_VARIANT: Record<HealthStatus, 'default' | 'outline' | 'destructive'> = {
  READY: 'default',
  WARMING: 'outline',
  NOT_READY: 'outline',
  FATAL: 'destructive',
};

interface InferenceHealthSectionProps {
  health: HealthReadyResponse;
}

export function InferenceHealthSection({ health }: InferenceHealthSectionProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('instructorInferenceHealthTitle')}</h2>
        <Badge variant={READINESS_BADGE_VARIANT[health.overall]}>{t(READINESS_LABEL_KEY[health.overall])}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs text-muted-foreground">
        <p>
          {t('instructorInferenceHealthRequiredLabel')}: {health.required_components.join(', ')}
        </p>
        <p>
          {t('instructorInferenceHealthModelProfileLabel')}: {health.model_profile}
        </p>
        {health.components.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {health.components.map((componentHealth) => (
              <li key={componentHealth.component}>
                <Badge variant={READINESS_BADGE_VARIANT[componentHealth.status]}>
                  {componentHealth.component}: {t(READINESS_LABEL_KEY[componentHealth.status])}
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
