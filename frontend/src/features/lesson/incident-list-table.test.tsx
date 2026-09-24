import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { ru } from '@/shared/i18n/ru';
import type { IncidentListItem } from '@/shared/api';
import { IncidentListTable } from './incident-list-table';

function makeItem(overrides: Partial<IncidentListItem>): IncidentListItem {
  return {
    session_id: 'sess-1',
    incident_id: 'inc-1',
    display_number: 36814851,
    lesson_id: 'lesson-1',
    card_status: 'REGISTERED',
    session_state: 'ACTIVE',
    arrived_at_utc: '2026-09-24T11:13:19Z',
    session_offset_ms: 5000,
    accept_deadline_offset_ms: 30000,
    fill_deadline_offset_ms: 180000,
    not_completed_deadline_offset_ms: null,
    classifier_code: '101',
    address_line_ru: 'Test City, Test St, 1',
    my_role_type: 'DDS',
    ...overrides,
  };
}

function renderTable(items: IncidentListItem[], consoleBasePath: '/operator' | '/dds' = '/dds') {
  return render(
    <MemoryRouter>
      <IncidentListTable items={items} consoleBasePath={consoleBasePath} />
    </MemoryRouter>,
  );
}

describe('IncidentListTable — renders card_status verbatim, never derives it', () => {
  it('shows the empty state with no rows', () => {
    renderTable([]);
    expect(screen.getByText(ru.incidentListEmpty)).toBeInTheDocument();
  });

  it('renders the server display_number and the server card_status label, not an outline badge', () => {
    renderTable([makeItem({ card_status: 'WORKED' })]);
    expect(screen.getByText(`${ru.incidentListNumberPrefix} 36814851`)).toBeInTheDocument();
    expect(screen.getByText(ru.lessonCardStatusWorked)).toBeInTheDocument();
  });

  it.each([
    ['NOT_NOTIFIED', ru.lessonCardStatusNotNotified],
    ['REFUSED', ru.lessonCardStatusRefused],
    ['NOT_COMPLETED', ru.lessonCardStatusNotCompleted],
  ] as const)('flags %s red (REQ-5312)', (status, label) => {
    renderTable([makeItem({ card_status: status })]);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute('data-variant', 'destructive');
  });

  it.each([
    ['REGISTERED', ru.lessonCardStatusRegistered],
    ['WORKED', ru.lessonCardStatusWorked],
    ['CHECKED', ru.lessonCardStatusChecked],
    ['COMPLETED', ru.lessonCardStatusCompleted],
  ] as const)('does not flag %s red', (status, label) => {
    renderTable([makeItem({ card_status: status })]);
    const badge = screen.getByText(label);
    expect(badge).toHaveAttribute('data-variant', 'outline');
  });

  it('links the open action to the session\'s existing console page (never a new one)', () => {
    renderTable([makeItem({ session_id: 'sess-42' })], '/operator');
    const link = screen.getByRole('link', { name: ru.incidentListOpenButton });
    expect(link).toHaveAttribute('href', '/operator/sess-42');
  });

  it('renders a dash for a deadline the server has not set yet, never computing one', () => {
    renderTable([makeItem({ not_completed_deadline_offset_ms: null })]);
    expect(screen.getAllByText(ru.incidentCountdownDash).length).toBeGreaterThan(0);
  });

  it('renders "overdue" once a set deadline is behind the session offset', () => {
    renderTable([makeItem({ accept_deadline_offset_ms: 1000, session_offset_ms: 5000 })]);
    expect(screen.getByText(ru.incidentCountdownOverdue)).toBeInTheDocument();
  });
});
