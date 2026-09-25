import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AppShell } from './app-shell';

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
