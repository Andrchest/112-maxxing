import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';

/** Fallback for any path not matched by a route group. */
export function NotFoundPage() {
  return (
    <AppShell title={t('notFoundTitle')}>
      <h1 className="text-lg font-semibold tracking-tight">{t('notFoundTitle')}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{t('notFoundHint')}</p>
    </AppShell>
  );
}
