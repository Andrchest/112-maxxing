import { AppShell } from '@/shared/ui/app-shell';
import { t } from '@/shared/i18n';

interface PlaceholderPageProps {
  title: string;
  /** Epic that owes the real screen, e.g. "E8". Shown as a TODO marker. */
  owningEpic: string;
  /** Header role chip (D4) — the caller's own account role, passed through unchanged; every
   * placeholder route is behind `RequireAuth`, so a real caller always has one. */
  role?: string;
}

/** Shared body for every route-group placeholder page scaffolded in E2.
 * Real consoles replace this per-feature starting at the epic named in
 * `owningEpic` (SPEC §47: nothing is silently stubbed). */
export function PlaceholderPage({ title, owningEpic, role }: PlaceholderPageProps) {
  return (
    <AppShell title={title} role={role}>
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{t('placeholderNotice')}</p>
      <p className="mt-1 font-mono text-xs text-muted-foreground">{`TODO(${owningEpic}): route implementation`}</p>
    </AppShell>
  );
}
