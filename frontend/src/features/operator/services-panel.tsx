// The services panel (SPEC §9/§10: `recipients.services`, "the services-getter" the handoff goes
// to). Edited only through the dedicated select/deselect commands — never through `setCardField`
// (D12 design decision #2) — and renders the server's returned selection after each command.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { useCardStore } from '@/entities/card';
import { useStageStore, hasAvailableAction } from '@/entities/stage';
import {
  deselectRecipientService,
  problemMessageRu,
  selectRecipientService,
  type ProblemCode,
  type ServiceType,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';

const SERVICE_TYPES: readonly ServiceType[] = ['FIRE_RESCUE', 'POLICE', 'AMBULANCE', 'GAS_SERVICE', 'UTILITY_EMERGENCY', 'EDDS'];

const SERVICE_TYPE_LABEL_KEY: Record<ServiceType, keyof typeof ru> = {
  FIRE_RESCUE: 'serviceTypeFireRescue',
  POLICE: 'serviceTypePolice',
  AMBULANCE: 'serviceTypeAmbulance',
  GAS_SERVICE: 'serviceTypeGasService',
  UTILITY_EMERGENCY: 'serviceTypeUtilityEmergency',
  EDDS: 'serviceTypeEdds',
};

interface ServicesPanelProps {
  sessionId: string;
}

export function ServicesPanel({ sessionId }: ServicesPanelProps) {
  const card = useCardStore((state) => state.card);
  const availableActions = useStageStore((state) => state.availableActions);
  const canSelect = hasAvailableAction(availableActions, 'select_services');
  const [pendingService, setPendingService] = useState<ServiceType | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const selectedValue = card?.values['recipients.services'];
  const selected = new Set(Array.isArray(selectedValue) ? (selectedValue as ServiceType[]) : []);

  async function toggle(serviceType: ServiceType): Promise<void> {
    setErrorMessage(null);
    setPendingService(serviceType);
    try {
      const response = selected.has(serviceType)
        ? await deselectRecipientService(sessionId, serviceType)
        : await selectRecipientService(sessionId, serviceType);
      useCardStore.getState().setCard(response.card);
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingService(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorServicesTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          {SERVICE_TYPES.map((serviceType) => {
            const isSelected = selected.has(serviceType);
            return (
              <Button
                key={serviceType}
                type="button"
                variant={isSelected ? 'default' : 'outline'}
                size="sm"
                disabled={!canSelect || pendingService !== null}
                aria-pressed={isSelected}
                onClick={() => void toggle(serviceType)}
              >
                {t(SERVICE_TYPE_LABEL_KEY[serviceType])}
              </Button>
            );
          })}
        </div>
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
