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
