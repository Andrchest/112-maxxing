// DDS notifications panel (SPEC §12; D5). `listNotifications`/`acknowledgeNotification` are the
// same endpoints the Operator 112 console's own panel uses (`features/operator/
// notifications-placeholder.tsx`) — the backend filters by the caller's role.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/shared/ui/badge';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { useNotificationStore, countUnacknowledged } from '@/entities/notification';
import { listNotifications, acknowledgeNotification, queryKeys, problemMessageRu, type ProblemCode } from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { notificationSeverityLabelRu } from './dds-labels';

const SEVERITY_BADGE_VARIANT: Record<string, 'outline' | 'secondary' | 'destructive'> = {
  INFO: 'outline',
  WARNING: 'secondary',
  CRITICAL: 'destructive',
};

interface NotificationsPanelProps {
  sessionId: string;
}

export function NotificationsPanel({ sessionId }: NotificationsPanelProps) {
  const items = useNotificationStore((state) => state.items);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.dds.notifications(sessionId),
    queryFn: () => listNotifications(sessionId),
  });

  useEffect(() => {
    if (query.data) {
      useNotificationStore.getState().setNotifications(query.data.items);
    }
  }, [query.data]);

  async function handleAcknowledge(notificationId: string): Promise<void> {
    setErrorMessage(null);
    setPendingId(notificationId);
    try {
      const acknowledged = await acknowledgeNotification(sessionId, notificationId);
      useNotificationStore.setState((state) => ({
        items: state.items.map((item) => (item.notification_id === acknowledged.notification_id ? acknowledged : item)),
      }));
    } catch (error) {
      setErrorMessage(error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown'));
    } finally {
      setPendingId(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorNotificationsTitle')}</h2>
        <Badge variant="outline" data-slot="unacknowledged-count">
          {t('ddsUnacknowledgedCountLabel')}: {countUnacknowledged(items)}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {items.length === 0 ? <p className="text-sm text-muted-foreground">{t('ddsNotificationsEmpty')}</p> : null}
        <ul className="flex flex-col gap-2">
          {items.map((item) => (
            <li key={item.notification_id} className="flex flex-col gap-1 rounded-lg border border-border p-2">
              <div className="flex items-center justify-between gap-2">
                <Badge variant={SEVERITY_BADGE_VARIANT[item.severity] ?? 'outline'}>{notificationSeverityLabelRu(item.severity)}</Badge>
                {item.acknowledged_at_offset_ms === null ? (
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    disabled={pendingId === item.notification_id}
                    onClick={() => void handleAcknowledge(item.notification_id)}
                  >
                    {t('ddsAcknowledgeNotificationButton')}
                  </Button>
                ) : null}
              </div>
              <p className="text-sm font-medium">{item.title_ru}</p>
              <p className="text-sm text-muted-foreground">{item.body_ru}</p>
            </li>
          ))}
        </ul>
        {errorMessage ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
