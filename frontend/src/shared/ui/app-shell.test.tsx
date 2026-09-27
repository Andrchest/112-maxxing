import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { AppShell } from './app-shell';
import { useAuthStore } from '@/entities/session';
import { ru } from '@/shared/i18n/ru';

// D4 addendum: a seeded demo account's own display_name_ru can equal its account role's own
// label (e.g. the trainee account is literally named "Стажёр") — the header must not then print
// the same word twice ("Стажёр Стажёр").
describe('AppShell — user label vs role chip (D4 addendum)', () => {
  it('shows both the user label and the role chip when they differ', () => {
    render(
      <AppShell title="Тренажёр 112" userLabel="Иванов И.И." role="Стажёр">
        <div />
      </AppShell>,
    );
    expect(screen.getByText('Иванов И.И.')).toBeInTheDocument();
    expect(screen.getByText('Стажёр')).toBeInTheDocument();
  });

  it('shows only the role chip, not a duplicate user label, when they are the same text', () => {
    render(
      <AppShell title="Тренажёр 112" userLabel="Стажёр" role="Стажёр">
        <div />
      </AppShell>,
    );
    const matches = screen.getAllByText('Стажёр');
    expect(matches).toHaveLength(1);
    expect(document.querySelector('[data-slot="user-label"]')).not.toBeInTheDocument();
    expect(document.querySelector('[data-slot="role-badge"]')).toBeInTheDocument();
  });

  it('shows no role chip and no user label when neither is given (signed-out page)', () => {
    render(
      <AppShell title="Страница не найдена">
        <div />
      </AppShell>,
    );
    expect(document.querySelector('[data-slot="role-badge"]')).not.toBeInTheDocument();
    expect(document.querySelector('[data-slot="user-label"]')).not.toBeInTheDocument();
  });
});

// I3 E4b (manager follow-up): a page with no socket must not look like a page whose socket
// dropped — `connectionIndicatorHidden` lets it opt out of the indicator entirely, without
// changing any existing caller's default rendering.
describe('AppShell — connection indicator (I3 E4b manager follow-up)', () => {
  it('shows the connection indicator by default, unchanged for every existing caller', () => {
    render(
      <AppShell title="Тренажёр 112">
        <div />
      </AppShell>,
    );
    expect(document.querySelector('[data-slot="connection-indicator"]')).toBeInTheDocument();
  });

  it('hides the connection indicator when the page declares it has no socket', () => {
    render(
      <AppShell title="Тренажёр 112" connectionIndicatorHidden>
        <div />
      </AppShell>,
    );
    expect(document.querySelector('[data-slot="connection-indicator"]')).not.toBeInTheDocument();
  });
});

// I4 E30 (71 §71.7): "the app shell shows an alerts badge for ADMIN" — a caller-supplied slot,
// omitted by every route but /admin (this component stays presentational, see its own doc comment).
describe('AppShell — adminAlertsBadge slot (I4 E30)', () => {
  it('renders nothing extra when the caller passes no badge (every non-admin route today)', () => {
    render(
      <AppShell title="Тренажёр 112">
        <div />
      </AppShell>,
    );
    expect(screen.queryByText('Оповещения')).not.toBeInTheDocument();
  });

  it('renders the caller-supplied badge when one is passed', () => {
    render(
      <AppShell title="Администрирование" adminAlertsBadge={<span>Оповещения: 2</span>}>
        <div />
      </AppShell>,
    );
    expect(screen.getByText('Оповещения: 2')).toBeInTheDocument();
  });
});

// I6: the «Выйти» button must be on every authenticated page. AppShell renders it itself (reading
// `useAuthStore` directly) instead of a per-page prop, so no caller can forget it — see the class
// doc comment for why this is the one deliberate exception to "purely presentational".
describe('AppShell — logout button (I6)', () => {
  afterEach(() => {
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('renders no logout button when signed out', () => {
    render(
      <MemoryRouter>
        <AppShell title="Тренажёр 112">
          <div />
        </AppShell>
      </MemoryRouter>,
    );
    expect(screen.queryByRole('button', { name: ru.logoutButton })).not.toBeInTheDocument();
  });

  it('renders exactly one logout button, after the other header items, when signed in', () => {
    useAuthStore.setState({
      token: 'jwt-token',
      isAuthenticated: true,
      user: { id: 'u1', username: 'trainee', display_name_ru: 'Стажёр', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
    });
    render(
      <MemoryRouter>
        <AppShell title="Тренажёр 112" userLabel="Стажёр" role="Стажёр">
          <div />
        </AppShell>
      </MemoryRouter>,
    );
    const buttons = screen.getAllByRole('button', { name: ru.logoutButton });
    expect(buttons).toHaveLength(1);
    // Header items render left to right; the logout button is the header's last child.
    const header = document.querySelector('header');
    expect(header?.lastElementChild?.lastElementChild).toBe(buttons[0]);
  });
});

// I6 UX (owner: «нет кнопок возврата из одного меню в другое»): the role's sections on every
// authenticated page, the current one highlighted, and a «← Назад» link on detail pages.
describe('AppShell — role navigation bar and back link (I6 UX)', () => {
  afterEach(() => {
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  function signInAs(user_role: 'TRAINEE' | 'INSTRUCTOR' | 'ADMIN'): void {
    useAuthStore.setState({
      token: 'jwt-token',
      isAuthenticated: true,
      user: { id: 'u1', username: 'u', display_name_ru: 'Пользователь', user_role, created_at: '2026-09-21T00:00:00Z' },
    });
  }

  function renderAt(path: string, backTo?: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <AppShell title="Тренажёр 112" backTo={backTo}>
          <div />
        </AppShell>
      </MemoryRouter>,
    );
  }

  function navLinks(): string[] {
    const nav = screen.getByRole('navigation', { name: ru.appNavAriaLabel });
    return Array.from(nav.querySelectorAll('a')).map((a) => a.textContent ?? '');
  }

  it('renders no navigation bar when signed out', () => {
    renderAt('/login');
    expect(screen.queryByRole('navigation', { name: ru.appNavAriaLabel })).not.toBeInTheDocument();
  });

  it('shows a trainee their three sections and highlights the current one (a console counts as «Мои занятия»)', () => {
    signInAs('TRAINEE');
    renderAt('/dds/sess-1');
    expect(navLinks()).toEqual([ru.appNavTraineeLessons, ru.appNavTraineeHistory, ru.appNavTraineeMaterials]);
    expect(screen.getByRole('link', { name: ru.appNavTraineeLessons })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: ru.appNavTraineeHistory })).not.toHaveAttribute('aria-current');
  });

  it('shows an instructor the five instructor sections, no admin link, «Сессии» current only on /instructor itself', () => {
    signInAs('INSTRUCTOR');
    renderAt('/instructor/lessons/lesson-1');
    expect(navLinks()).toEqual([
      ru.appNavInstructorLessons,
      ru.appNavInstructorSessions,
      ru.appNavInstructorStatistics,
      ru.appNavInstructorScenarios,
      ru.appNavInstructorMaterials,
    ]);
    expect(screen.getByRole('link', { name: ru.appNavInstructorLessons })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: ru.appNavInstructorSessions })).not.toHaveAttribute('aria-current');
    expect(screen.queryByRole('link', { name: ru.appNavAdmin })).not.toBeInTheDocument();
  });

  it('shows an admin «Администрирование» plus the instructor sections', () => {
    signInAs('ADMIN');
    renderAt('/admin');
    expect(navLinks()[0]).toBe(ru.appNavAdmin);
    expect(navLinks()).toHaveLength(6);
    expect(screen.getByRole('link', { name: ru.appNavAdmin })).toHaveAttribute('aria-current', 'page');
  });

  it('renders the «← Назад» link to the parent list only when the page passes one', () => {
    signInAs('INSTRUCTOR');
    const { unmount } = renderAt('/instructor/lessons/lesson-1', '/instructor/lessons');
    expect(screen.getByRole('link', { name: ru.appBackLink })).toHaveAttribute('href', '/instructor/lessons');
    unmount();
    renderAt('/instructor/lessons');
    expect(screen.queryByRole('link', { name: ru.appBackLink })).not.toBeInTheDocument();
  });
});
