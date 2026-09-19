import type { ReactNode } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Separator } from '@/shared/ui/separator';
import { t } from '@/shared/i18n';

interface AppShellProps {
  /** Current screen title, shown next to the product name. */
  title: string;
  /** Trainee's current role in this session, if any has been assigned yet. */
  role?: string;
  children: ReactNode;
}

/**
 * Dense, dark "operations console" chrome shared by every route (D12,
 * SPEC §32): product name, role badge and a connection-status placeholder
 * (wired to the realtime channel starting E7). There is no chat UI here or
 * anywhere else in the app — the caller's dialogue is a phone widget added
 * in E11, not a message thread.
 */
export function AppShell({ title, role, children }: AppShellProps) {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex h-11 shrink-0 items-center gap-3 border-b border-border bg-card px-4">
        <span className="text-sm font-semibold tracking-tight">{t('appName')}</span>
        <Separator orientation="vertical" className="h-5" />
        <span className="font-mono text-xs text-muted-foreground">{title}</span>
        <div className="ml-auto flex items-center gap-3">
          <Badge variant="outline" className="font-mono text-xs" data-slot="role-badge">
            {role ?? t('roleBadgeNone')}
          </Badge>
          <span
            className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground"
            data-slot="connection-indicator"
          >
            <span className="size-2 rounded-full bg-muted-foreground/50" aria-hidden="true" />
            {t('connectionPlaceholder')}
          </span>
        </div>
      </header>
      <main className="flex-1 overflow-auto p-4">{children}</main>
    </div>
  );
}
