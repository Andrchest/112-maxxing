import { Link, useLocation } from 'react-router';
import { t } from '@/shared/i18n';
import type { ru } from '@/shared/i18n/ru';
import type { UserRole } from '@/shared/api';
import { cn } from 'cn';

interface NavItem {
  to: string;
  labelKey: keyof typeof ru;
  /** Path prefixes (besides `to` itself) under which this item is the current section. */
  activePrefixes: readonly string[];
  /** When `true`, `to` itself matches only exactly (its own prefix is shared by other items). */
  exact?: boolean;
}

const TRAINEE_ITEMS: readonly NavItem[] = [
  { to: '/sessions', labelKey: 'appNavTraineeLessons', activePrefixes: ['/sessions', '/dds', '/operator'] },
  { to: '/history', labelKey: 'appNavTraineeHistory', activePrefixes: ['/history', '/report'] },
  { to: '/materials', labelKey: 'appNavTraineeMaterials', activePrefixes: ['/materials'] },
];

const INSTRUCTOR_ITEMS: readonly NavItem[] = [
  { to: '/instructor/lessons', labelKey: 'appNavInstructorLessons', activePrefixes: ['/instructor/lessons', '/instructor/board'] },
  { to: '/instructor', labelKey: 'appNavInstructorSessions', activePrefixes: ['/instructor/sessions'], exact: true },
  { to: '/instructor/statistics', labelKey: 'appNavInstructorStatistics', activePrefixes: ['/instructor/statistics'] },
  { to: '/instructor/scenarios', labelKey: 'appNavInstructorScenarios', activePrefixes: ['/instructor/scenarios'] },
  { to: '/instructor/materials', labelKey: 'appNavInstructorMaterials', activePrefixes: ['/instructor/materials'] },
];

/** ADMIN's own screen plus the instructor links — `/instructor/*`'s route guard admits ADMIN too
 * (`app/router.tsx`), so every link here opens. */
const ADMIN_ITEMS: readonly NavItem[] = [
  { to: '/admin', labelKey: 'appNavAdmin', activePrefixes: ['/admin'] },
  ...INSTRUCTOR_ITEMS,
];

const ITEMS_BY_ROLE: Record<UserRole, readonly NavItem[]> = {
  TRAINEE: TRAINEE_ITEMS,
  INSTRUCTOR: INSTRUCTOR_ITEMS,
  ADMIN: ADMIN_ITEMS,
};

function underPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

function isActive(item: NavItem, pathname: string): boolean {
  if (item.exact ? pathname === item.to : underPrefix(pathname, item.to)) return true;
  return item.activePrefixes.some((prefix) => underPrefix(pathname, prefix));
}

/** Parent list a trainee's or an instructor's session report returns to (I6 UX «← Назад»): the
 * trainee's own history, or the instructor's lesson when the session is a lesson card. */
export function reportBackTo(role: UserRole | undefined, lessonId: string | null | undefined): string {
  if (role === 'TRAINEE') return '/history';
  return lessonId ? `/instructor/lessons/${lessonId}` : '/instructor';
}

/**
 * I6 UX (owner: «нет кнопок возврата из одного меню в другое»): the role's sections, shown in the
 * app shell header on every authenticated page, with the current section highlighted. Only routes
 * the role's own guard admits (`app/router.tsx`) are listed.
 */
export function AppNav({ role }: { role: UserRole }) {
  const { pathname } = useLocation();
  const items = ITEMS_BY_ROLE[role];
  return (
    <nav aria-label={t('appNavAriaLabel')} className="flex min-w-0 items-center gap-1 overflow-x-auto" data-slot="app-nav" data-tour="app-nav">
      {items.map((item) => {
        const active = isActive(item, pathname);
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'shrink-0 rounded-md px-2 py-1 text-xs whitespace-nowrap transition-colors hover:bg-accent hover:text-accent-foreground',
              active ? 'bg-accent font-semibold text-accent-foreground' : 'text-muted-foreground',
            )}
          >
            {t(item.labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}
