import type { ReactNode } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Separator } from '@/shared/ui/separator';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { ConnectionStatus } from '@/shared/realtime/ws-client';
import type { HealthStatus } from '@/shared/api';

const CONNECTION_LABEL_KEY: Record<ConnectionStatus, keyof typeof ru> = {
  idle: 'connectionPlaceholder',
  connecting: 'connectionConnecting',
  reconnecting: 'connectionConnecting',
  open: 'connectionConnected',
  closed: 'connectionDisconnected',
};

const CONNECTION_DOT_CLASS: Record<ConnectionStatus, string> = {
  idle: 'bg-muted-foreground/50',
  connecting: 'bg-amber-500 animate-pulse',
  reconnecting: 'bg-amber-500 animate-pulse',
  open: 'bg-emerald-500',
  closed: 'bg-muted-foreground/50',
};

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

interface AppShellProps {
  /** Current screen title, shown next to the product name. */
  title: string;
  /** Trainee's current role in this session, if any has been assigned yet. */
  role?: string;
  /** Signed-in account's display name, when the caller has that data (authenticated routes). */
  userLabel?: string;
  /** Realtime WebSocket status (D8, HLD §40); omitted where no page connects one yet. */
  connectionStatus?: ConnectionStatus;
  /** `GET /health/ready` overall status (SPEC §37); omitted while it has not loaded yet. */
  readiness?: HealthStatus;
  /**
   * Whether the connection indicator renders at all (default `true`, unchanged for every
   * existing caller). `connectionStatus` and `connectionIndicatorHidden` are independent: a page
   * that never opens a socket (a list/dashboard route, I3 E4b) sets this `false` instead of
   * relying on the `idle` default, because `idle`'s label (`connectionPlaceholder`) and dot are
   * visually identical to `closed` (a socket that really did drop) — showing either on a page
   * with no socket at all reads as "lost connection" when nothing was ever connected.
   */
  connectionIndicatorHidden?: boolean;
  children: ReactNode;
}

/**
 * Dense, dark "operations console" chrome shared by every route (D12,
 * SPEC §32): product name, user + role badge, connection status and
 * inference readiness. There is no chat UI here or anywhere else in the
 * app — the caller's dialogue is a phone widget added in E11, not a
 * message thread. Purely presentational: every value it shows is passed in
 * by the caller, which is the layer allowed to fetch or subscribe to it.
 */
export function AppShell({
  title,
  role,
  userLabel,
  connectionStatus,
  readiness,
  connectionIndicatorHidden = false,
  children,
}: AppShellProps) {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <header className="flex h-11 shrink-0 items-center gap-3 border-b border-border bg-card px-4">
        <span className="text-sm font-semibold tracking-tight">{t('appName')}</span>
        <Separator orientation="vertical" className="h-5" />
        <span className="font-mono text-xs text-muted-foreground">{title}</span>
        <div className="ml-auto flex items-center gap-3">
          {/* D4 addendum: the seeded demo accounts' own `display_name_ru` can equal the account
              role's own label (e.g. the trainee account is literally named "Стажёр"), which would
              otherwise print the same word twice ("Стажёр Стажёр"). The role chip already carries
              that information, so the separate user-label span is dropped only in that case —
              a genuinely different display name (the common case) still shows both. */}
          {userLabel && userLabel !== role ? (
            <span className="font-mono text-xs text-muted-foreground" data-slot="user-label">
              {userLabel}
            </span>
          ) : null}
          {role ? (
            <Badge variant="outline" className="font-mono text-xs" data-slot="role-badge">
              {role}
            </Badge>
          ) : null}
          {readiness ? (
            <Badge
              variant={READINESS_BADGE_VARIANT[readiness]}
              className="font-mono text-xs"
              data-slot="readiness-badge"
            >
              {t('readinessLabel')}: {t(READINESS_LABEL_KEY[readiness])}
            </Badge>
          ) : null}
          {connectionIndicatorHidden ? null : (
            <span
              className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground"
              data-slot="connection-indicator"
            >
              <span
                className={`size-2 rounded-full ${CONNECTION_DOT_CLASS[connectionStatus ?? 'idle']}`}
                aria-hidden="true"
              />
              {t(CONNECTION_LABEL_KEY[connectionStatus ?? 'idle'])}
            </span>
          )}
        </div>
      </header>
      <main className="flex-1 overflow-auto p-4">{children}</main>
    </div>
  );
}
