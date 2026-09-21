import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';

/** Right-column placeholder (SPEC §9/§32 console layout; D12). `NOTIFICATION_CREATED` /
 * `NOTIFICATION_ACKNOWLEDGED` land in `docs/hld/40-realtime-protocol.md` §40.4 rows 37-38, but no
 * epic before E10 owns the DDS-triggered notifications this panel would render. */
export function NotificationsPlaceholder() {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorNotificationsTitle')}</h2>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{t('placeholderNotice')}</p>
        <p className="mt-1 font-mono text-xs text-muted-foreground">TODO(E10): notifications panel</p>
      </CardContent>
    </Card>
  );
}
