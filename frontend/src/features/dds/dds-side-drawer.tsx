// I3 E5c (manager review): Уведомления / Радиообмен / Отправить статус have no counterpart on the
// reference ДДС screens (ui-check D-9/D-10) — under `dds_mode: MEMO_STATUSES` they move into a
// collapsible drawer, closed by default, so the main view matches the reference's shape. Opening
// it is the only way to reach them; nothing here changes what those three panels themselves do.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { NotificationsPanel } from './notifications-panel';
import { RadioLog } from './radio-log';
import { StatusUpdateForm } from './status-update-form';

interface DdsSideDrawerProps {
  sessionId: string;
}

export function DdsSideDrawer({ sessionId }: DdsSideDrawerProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button type="button" variant="outline" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {t('ddsSideDrawerToggleButton')}
      </Button>
      {open ? (
        <div
          className="fixed inset-y-0 right-0 z-20 flex w-80 flex-col gap-4 overflow-y-auto border-l border-border bg-background p-4 shadow-lg"
          data-slot="dds-side-drawer"
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-heading text-base leading-snug font-medium">{t('ddsSideDrawerTitle')}</h2>
            <Button type="button" size="sm" variant="outline" onClick={() => setOpen(false)}>
              {t('ddsSideDrawerCloseButton')}
            </Button>
          </div>
          <NotificationsPanel sessionId={sessionId} />
          <RadioLog sessionId={sessionId} />
          <StatusUpdateForm sessionId={sessionId} />
        </div>
      ) : null}
    </>
  );
}
