import type { ReactNode } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Separator } from '@/shared/ui/separator';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import type { ConnectionStatus } from '@/shared/realtime/ws-client';
import type { HealthStatus } from '@/shared/api';
import { useAuthStore } from '@/entities/session';
import { LogoutButton } from '@/features/auth/logout-button';

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
  /**
   * I3 E7a (D20, C9): renders this route in the organizer's reference look (light theme, `.reference-
   * light`, `src/index.css`) instead of D12's dense dark console — scoped per route, never a global
   * flip. Set only by the screens with a reference counterpart (the 112 operator console/card, the
   * ДДС workstation, the 112 «реестр» / ДДС «Список происшествий»); every other route omits it and
   * keeps the dark look.
   */
  referenceTheme?: boolean;
  /**
   * I3 E7a (manager review): a route with its own pinned-to-the-viewport-bottom bar (the 112
   * «Службы:» bar, the ДДС services tab bar) needs `main` itself to stop scrolling and instead
   * hand that job to the caller's own inner scroll region, so the bar sits at the true viewport
   * bottom always — including when the content above it is shorter than the viewport, which a
   * `position: sticky` bar alone cannot do (it only pins once there is something to scroll).
   * Default `false`: `main` scrolls and pads itself, unchanged for every other route.
   */
  fillHeight?: boolean;
  /**
   * I4 E30 (71 §71.7: "the app shell shows an alerts badge for ADMIN"): an optional slot the
   * caller renders its own already-fetched content into — this component stays presentational
   * and never fetches anything itself (see the class doc). Only `AdminPage` (`/admin`) passes one
   * today; every other route omits it, unchanged.
   */
  adminAlertsBadge?: ReactNode;
  children: ReactNode;
}

/**
 * Dense, dark "operations console" chrome shared by every route (D12,
 * SPEC §32): product name, user + role badge, connection status and
 * inference readiness. There is no chat UI here or anywhere else in the
 * app — the caller's dialogue is a phone widget added in E11, not a
 * message thread. Purely presentational: every value it shows is passed in
 * by the caller, which is the layer allowed to fetch or subscribe to it.
 *
 * I6 (logout on every authenticated page): the one deliberate exception is the «Выйти» button —
 * it reads `useAuthStore` itself and renders whenever a user is signed in, instead of a per-page
 * prop, so that every route sharing this shell gets it for free and cannot forget it. There is no
 * frontend import-boundary check (D2's `check_imports.py` covers `backend/`/`workers/`/
 * `benchmarks/` only), so this shared component importing a `features/auth` component is allowed.
 */
export function AppShell({
  title,
  role,
  userLabel,
  connectionStatus,
  readiness,
  connectionIndicatorHidden = false,
  referenceTheme = false,
  fillHeight = false,
  adminAlertsBadge,
  children,
}: AppShellProps) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return (
    <div
      className={`flex min-h-svh flex-col bg-background text-foreground ${referenceTheme ? 'reference-light' : ''}`}
      data-theme={referenceTheme ? 'reference-light' : undefined}
    >
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
          {adminAlertsBadge}
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
          {isAuthenticated ? <LogoutButton /> : null}
        </div>
      </header>
      <main className={fillHeight ? 'flex min-h-0 flex-1 flex-col overflow-hidden' : 'flex-1 overflow-auto p-4'}>{children}</main>
    </div>
  );
}
