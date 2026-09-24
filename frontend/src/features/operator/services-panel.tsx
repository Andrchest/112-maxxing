// The services panel (SPEC §9/§10; I3 E2b′, HLD 70 §70.6.4, C10): the card's notification list —
// the routing resolver's automatic services plus the trainee's manual additions — and a modal
// picker with search over the service catalog (`GET /reference/services`) to add one more.
//
// Every value here is server data. «авто» is the `auto_services` of the log's latest
// `RECIPIENTS_RESOLVED` (the REST history of `listSessionEvents` merged with the live event store,
// as the transcript panel does); «вручную» is `recipients.services`, edited only through the
// select/deselect commands (D12 design decision #2), never through `setCardField`. Under a v2
// card nobody removes a service (memo p.14, REQ-5275): there is no remove control, and the server
// answers `409 SERVICE_REMOVAL_FORBIDDEN` anyway. Under a v1 card the remove control stays.
//
// Markup is deliberately plain and semantic (a list, a dialog, a search box): E7a restyles it to
// the reference look.
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/shared/ui/dialog';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { useCardStore } from '@/entities/card';
import { serviceLabelRu } from '@/entities/service-catalog';
import { useSessionEventsStore } from '@/entities/session';
import { useStageStore, hasAvailableAction } from '@/entities/stage';
import {
  deselectRecipientService,
  listReferenceServices,
  listSessionEvents,
  problemMessageRu,
  queryKeys,
  selectRecipientService,
  type ProblemCode,
  type ServiceCatalogEntry,
  type ServiceId,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { latestResolution } from './latest-resolution';

interface ServicesPanelProps {
  sessionId: string;
}

function matches(entry: ServiceCatalogEntry, needle: string): boolean {
  if (!needle) return true;
  return [entry.name_ru, entry.full_name_ru, entry.id].some((text) => text.toLocaleLowerCase('ru').includes(needle));
}

export function ServicesPanel({ sessionId }: ServicesPanelProps) {
  const card = useCardStore((state) => state.card);
  const availableActions = useStageStore((state) => state.availableActions);
  const liveEvents = useSessionEventsStore((state) => state.events);
  const canSelect = hasAvailableAction(availableActions, 'select_services');
  const [pendingService, setPendingService] = useState<ServiceId | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState('');

  const historyQuery = useQuery({
    queryKey: [...queryKeys.sessions.detail(sessionId), 'recipients-resolved'],
    queryFn: () => listSessionEvents(sessionId, { eventType: ['RECIPIENTS_RESOLVED'], limit: 1000 }),
  });
  const catalogQuery = useQuery({
    queryKey: queryKeys.reference.services('picker'),
    queryFn: () => listReferenceServices(),
    enabled: pickerOpen,
    staleTime: Infinity,
  });

  const resolution = useMemo(
    () => latestResolution([...(historyQuery.data?.items ?? []), ...liveEvents]),
    [historyQuery.data, liveEvents],
  );
  const removalAllowed = (card?.card_schema ?? 'v1') === 'v1';
  const manualValue = card?.values['recipients.services'];
  const manual = Array.isArray(manualValue) ? (manualValue as ServiceId[]) : [];
  const auto = resolution?.auto ?? [];
  const listed = [...auto, ...manual.filter((service) => !auto.includes(service))];
  const needle = search.trim().toLocaleLowerCase('ru');
  const choices = (catalogQuery.data ?? []).filter((entry) => matches(entry, needle));

  async function run(serviceType: ServiceId, remove: boolean): Promise<void> {
    setErrorMessage(null);
    setPendingService(serviceType);
    try {
      const response = remove
        ? await deselectRecipientService(sessionId, serviceType)
        : await selectRecipientService(sessionId, serviceType);
      useCardStore.getState().setCard(response.card);
      if (!remove) setPickerOpen(false);
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingService(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorServicesTitle')}</h2>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canSelect || pendingService !== null}
          onClick={() => setPickerOpen(true)}
        >
          {t('operatorServicesAdd')}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {listed.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('operatorServicesEmpty')}</p>
        ) : (
          <ul aria-label={t('operatorServicesTitle')} className="flex flex-col gap-1">
            {listed.map((service) => {
              const isAuto = auto.includes(service);
              return (
                <li key={service} className="flex items-center gap-2 text-sm">
                  <span>{serviceLabelRu(service)}</span>
                  <Badge variant={isAuto ? 'secondary' : 'outline'}>
                    {isAuto ? t('operatorServicesAuto') : t('operatorServicesManual')}
                  </Badge>
                  {removalAllowed && !isAuto ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={!canSelect || pendingService !== null}
                      aria-label={`${t('operatorServicesRemove')}: ${serviceLabelRu(service)}`}
                      onClick={() => void run(service, true)}
                    >
                      {t('operatorServicesRemove')}
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        {resolution && resolution.informed.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            {t('operatorServicesInformed')}: {resolution.informed.map((service) => serviceLabelRu(service)).join(', ')}
          </p>
        ) : null}
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('operatorServicesPickerTitle')}</DialogTitle>
            {!removalAllowed ? <DialogDescription>{t('operatorServicesPickerDescription')}</DialogDescription> : null}
          </DialogHeader>
          <div className="flex flex-col gap-1">
            <Label htmlFor="services-picker-search">{t('operatorServicesSearchLabel')}</Label>
            <Input
              id="services-picker-search"
              type="search"
              value={search}
              placeholder={t('operatorServicesSearchPlaceholder')}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <ul aria-label={t('operatorServicesPickerTitle')} className="flex max-h-72 flex-col gap-1 overflow-y-auto">
            {choices.map((entry) => {
              const already = listed.includes(entry.id);
              return (
                <li key={entry.id}>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="w-full justify-start"
                    disabled={already || !canSelect || pendingService !== null}
                    onClick={() => void run(entry.id, false)}
                  >
                    {entry.name_ru}
                    {already ? ` — ${t('operatorServicesAlreadyListed')}` : ''}
                  </Button>
                </li>
              );
            })}
          </ul>
          {catalogQuery.isSuccess && choices.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('operatorServicesPickerNothingFound')}</p>
          ) : null}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
