// I7 E56: the tutorial's entry points in the app shell — the header «Обучение» button, the
// first-login card and the user menu with the «Подсказки для новичков» switch.
import { useLocation } from 'react-router';
import { DropdownMenu } from 'radix-ui';
import { Check, CircleUserRound, GraduationCap } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';
import { useTourStore } from './tour-store';
import { useHintsEnabled, useTourPreferences, useTourSeen } from './tour-preferences';
import { TOUR_BY_ROLE, tourPlanFor } from './tours';

/** Header button «Обучение»: (re)starts the role's tour — from this page's own segment when the
 * page has one, else from the beginning. */
export function TourButton() {
  const user = useAuthStore((state) => state.user);
  const start = useTourStore((state) => state.start);
  const { pathname } = useLocation();
  if (!user) return null;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      data-tour="tour-button"
      onClick={() => {
        const plan = tourPlanFor(user.user_role, pathname);
        start(plan.steps, plan.index);
      }}
    >
      <GraduationCap aria-hidden="true" />
      {t('tourStartButton')}
    </Button>
  );
}

/**
 * Non-blocking first-login card, bottom-right: «Впервые здесь? Пройдите короткое обучение» with
 * «Начать обучение» / «Не сейчас». Either answer is remembered per user id (localStorage); not a
 * dialog — the page stays fully usable under and around it, and `AppShell` pads the page bottom
 * while it shows so nothing stays hidden beneath it.
 */
export function FirstLoginCard() {
  const user = useAuthStore((state) => state.user);
  const seen = useTourSeen(user?.id);
  const tourActive = useTourStore((state) => state.active);
  const start = useTourStore((state) => state.start);
  const markSeen = useTourPreferences((state) => state.markSeen);
  if (!user || seen || tourActive) return null;
  return (
    <section
      aria-label={t('tourFirstLoginRegionLabel')}
      data-slot="tour-first-login"
      className="fixed right-4 bottom-4 z-40 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-xl border border-border bg-popover p-3 text-popover-foreground shadow-lg"
    >
      <p className="flex items-center gap-2 text-sm font-semibold">
        <GraduationCap aria-hidden="true" className="size-4 shrink-0" />
        {t('tourFirstLoginTitle')}
      </p>
      <p className="text-sm text-muted-foreground">{t('tourFirstLoginText')}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          onClick={() => {
            markSeen(user.id);
            start(TOUR_BY_ROLE[user.user_role], 0);
          }}
        >
          {t('tourFirstLoginStart')}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => markSeen(user.id)}>
          {t('tourFirstLoginLater')}
        </Button>
      </div>
    </section>
  );
}

/** Whether `FirstLoginCard` is showing for the signed-in user (the shell pads the page for it). */
export function useFirstLoginCardShown(): boolean {
  const user = useAuthStore((state) => state.user);
  const seen = useTourSeen(user?.id);
  const tourActive = useTourStore((state) => state.active);
  return Boolean(user) && !seen && !tourActive;
}

/** The user menu (icon button in the header): the «Подсказки для новичков» switch, default off. */
export function UserMenu() {
  const user = useAuthStore((state) => state.user);
  const hintsEnabled = useHintsEnabled(user?.id);
  const setHints = useTourPreferences((state) => state.setHints);
  if (!user) return null;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button type="button" variant="ghost" size="icon-sm" aria-label={t('userMenuButton')} data-tour="user-menu">
          <CircleUserRound aria-hidden="true" />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-50 min-w-56 rounded-lg border border-border bg-popover p-1 text-sm text-popover-foreground shadow-md"
        >
          <DropdownMenu.CheckboxItem
            checked={hintsEnabled}
            onCheckedChange={(checked) => setHints(user.id, checked === true)}
            onSelect={(event) => event.preventDefault()}
            className="flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 outline-none select-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground"
          >
            <span className="flex size-4 items-center justify-center rounded-sm border border-border">
              <DropdownMenu.ItemIndicator>
                <Check className="size-3" aria-hidden="true" />
              </DropdownMenu.ItemIndicator>
            </span>
            {t('userMenuHintsToggle')}
          </DropdownMenu.CheckboxItem>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
