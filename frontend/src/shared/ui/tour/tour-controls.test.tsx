// I7 E56: the tutorial's entry points — the first-login card (remembered per user, harmless without
// storage), the header «Обучение» button (restarts the role's tour from the current page) and the
// «Подсказки для новичков» switch in the user menu (default off; on shows the «?» hints).
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuthStore, type UserAccount } from '@/entities/session';
import { AppShell } from '@/shared/ui/app-shell';
import { TooltipProvider } from '@/shared/ui/tooltip';
import { Hint } from './hint';
import { useTourPreferences } from './tour-preferences';
import { useTourStore } from './tour-store';
import { ADMIN_TOUR, INSTRUCTOR_TOUR, TRAINEE_TOUR, tourPlanFor } from './tours';

function signIn(role: UserAccount['user_role'], id = 'u1'): void {
  useAuthStore.setState({
    isAuthenticated: true,
    token: 'jwt',
    user: { id, username: 'u', display_name_ru: 'Иванов', user_role: role, created_at: '2026-09-29T00:00:00Z' },
  });
}

function renderShell(path = '/sessions', options: { fillHeight?: boolean } = {}) {
  return render(
    <TooltipProvider>
      <MemoryRouter initialEntries={[path]}>
        <AppShell title="Тренажёр 112" fillHeight={options.fillHeight}>
          <label htmlFor="field">Поле</label>
          <Hint text="Одна фраза подсказки." />
          <input id="field" />
        </AppShell>
      </MemoryRouter>
    </TooltipProvider>,
  );
}

const CARD = { name: 'Первое знакомство' };

describe('first-login card (I7 E56)', () => {
  beforeEach(() => {
    localStorage.clear();
    useTourPreferences.setState({ seen: {}, hints: {} });
    signIn('TRAINEE');
  });

  afterEach(() => {
    act(() => useTourStore.getState().stop());
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('shows «Впервые здесь? Пройдите короткое обучение» as a non-modal region, not a dialog', () => {
    renderShell();
    const card = screen.getByRole('region', CARD);
    expect(card).toHaveTextContent('Впервые здесь?');
    expect(card).toHaveTextContent('Пройдите короткое обучение');
    expect(screen.getByRole('button', { name: 'Начать обучение' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    // The page stays usable and gets a bottom spacer so nothing hides under the card.
    expect(screen.getByLabelText('Поле')).toBeEnabled();
    expect(document.querySelector('[data-slot="tour-first-login-spacer"]')).toBeInTheDocument();
  });

  it('«Не сейчас» hides it and remembers that per user id', async () => {
    const view = renderShell();
    await userEvent.click(screen.getByRole('button', { name: 'Не сейчас' }));
    expect(screen.queryByRole('region', CARD)).not.toBeInTheDocument();
    expect(localStorage.getItem('tour.seen.u1')).toBe('1');

    view.unmount();
    useTourPreferences.setState({ seen: {}, hints: {} });
    const again = renderShell();
    expect(screen.queryByRole('region', CARD)).not.toBeInTheDocument();

    // Another user on the same browser still gets the card.
    again.unmount();
    signIn('TRAINEE', 'u2');
    renderShell();
    expect(screen.getByRole('region', CARD)).toBeInTheDocument();
  });

  it('«Начать обучение» starts the role’s tour from its beginning', async () => {
    signIn('INSTRUCTOR');
    renderShell('/instructor/statistics');
    await userEvent.click(screen.getByRole('button', { name: 'Начать обучение' }));
    const tour = useTourStore.getState();
    expect(tour.active).toBe(true);
    expect(tour.steps).toBe(INSTRUCTOR_TOUR);
    expect(tour.index).toBe(0);
    expect(localStorage.getItem('tour.seen.u1')).toBe('1');
    expect(screen.queryByRole('region', CARD)).not.toBeInTheDocument();
  });

  it('shows again (harmlessly) when localStorage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    renderShell();
    expect(screen.getByRole('region', CARD)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Не сейчас' }));
    expect(screen.queryByRole('region', CARD)).not.toBeInTheDocument();
  });

  it('is not offered on a full-height console (its pinned bottom bar sits there)', () => {
    renderShell('/dds/00000000-0000-0000-0000-000000000000', { fillHeight: true });
    expect(screen.queryByRole('region', CARD)).not.toBeInTheDocument();
  });
});

describe('header «Обучение» button (I7 E56)', () => {
  beforeEach(() => {
    localStorage.setItem('tour.seen.u1', '1');
    useTourPreferences.setState({ seen: {}, hints: {} });
  });

  afterEach(() => {
    act(() => useTourStore.getState().stop());
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    localStorage.clear();
  });

  it('restarts the role’s tour from the current page’s own segment', async () => {
    signIn('TRAINEE');
    renderShell('/history');
    await userEvent.click(screen.getByRole('button', { name: 'Обучение' }));
    const tour = useTourStore.getState();
    expect(tour.active).toBe(true);
    expect(tour.steps).toBe(TRAINEE_TOUR);
    expect(tour.steps[tour.index]?.id).toBe('trainee-report');
  });

  it('starts from the beginning on a page with no segment, any number of times', async () => {
    signIn('ADMIN');
    renderShell('/report/00000000-0000-0000-0000-000000000000');
    await userEvent.click(screen.getByRole('button', { name: 'Обучение' }));
    expect(useTourStore.getState().steps).toBe(ADMIN_TOUR);
    expect(useTourStore.getState().index).toBe(0);
    act(() => useTourStore.getState().stop());
    await userEvent.click(screen.getByRole('button', { name: 'Обучение' }));
    expect(useTourStore.getState().active).toBe(true);
  });

  it('plans per role and page: live consoles, an admin on an instructor page', () => {
    const dds = tourPlanFor('TRAINEE', '/dds/0f0e0d0c-0b0a-0908-0706-050403020100');
    expect(dds.steps[dds.index]?.id).toBe('trainee-dds-header');
    const lesson = tourPlanFor('INSTRUCTOR', '/instructor/lessons/0f0e0d0c-0b0a-0908-0706-050403020100');
    expect(lesson.steps[lesson.index]?.id).toBe('instructor-lesson-start');
    const adminOnScenarios = tourPlanFor('ADMIN', '/instructor/scenarios');
    expect(adminOnScenarios.steps).toBe(INSTRUCTOR_TOUR);
    expect(adminOnScenarios.steps[adminOnScenarios.index]?.id).toBe('instructor-scenarios');
  });
});

describe('«Подсказки для новичков» (I7 E56)', () => {
  beforeEach(() => {
    localStorage.setItem('tour.seen.u1', '1');
    useTourPreferences.setState({ seen: {}, hints: {} });
    signIn('INSTRUCTOR');
  });

  afterEach(() => {
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    localStorage.clear();
  });

  it('is off by default: no «?» next to the fields', () => {
    renderShell('/instructor/lessons');
    expect(document.querySelector('[data-slot="beginner-hint"]')).not.toBeInTheDocument();
  });

  it('the user-menu switch turns the «?» hints on (with the sentence as its name) and off again', async () => {
    renderShell('/instructor/lessons');
    // Radix opens its menu on a real pointer press; jsdom has no PointerEvent, so the keyboard way.
    screen.getByRole('button', { name: 'Меню пользователя' }).focus();
    await userEvent.keyboard('{Enter}');
    const toggle = await screen.findByRole('menuitemcheckbox', { name: 'Подсказки для новичков' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    // The menu stays open after the switch (several toggles in a row); Esc closes it.
    await userEvent.keyboard('{Escape}');
    expect(await screen.findByRole('button', { name: 'Подсказка: Одна фраза подсказки.' })).toBeInTheDocument();
    expect(localStorage.getItem('tour.hints.u1')).toBe('1');
    // The field's own label is untouched by the hint beside it.
    expect(screen.getByLabelText('Поле')).toBeInTheDocument();

    screen.getByRole('button', { name: 'Меню пользователя' }).focus();
    await userEvent.keyboard('{Enter}');
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: 'Подсказки для новичков' }));
    expect(document.querySelector('[data-slot="beginner-hint"]')).not.toBeInTheDocument();
    expect(localStorage.getItem('tour.hints.u1')).toBe('0');
  });
});
