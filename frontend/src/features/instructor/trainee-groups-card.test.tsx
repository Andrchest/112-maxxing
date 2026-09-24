import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TraineeGroupsCard } from './trainee-groups-card';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

const TRAINEES = {
  items: ['a', 'b', 'c'].map((suffix) => ({
    id: `trainee-${suffix}`,
    username: `trainee-${suffix}`,
    display_name_ru: `Trainee ${suffix.toUpperCase()}`,
    user_role: 'TRAINEE',
    created_at: '2026-09-21T00:00:00Z',
  })),
  total: 3,
};

function renderCard() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TraineeGroupsCard />
    </QueryClientProvider>,
  );
}

describe('TraineeGroupsCard — instructor trainee groups (70 §70.3.7)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('creates a group of the ticked trainees, lists it and deletes it', async () => {
    const user = userEvent.setup();
    let groups: unknown[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/users?role=TRAINEE') return jsonResponse(TRAINEES);
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse({ items: groups, total: groups.length });
      if (url === '/api/v1/trainee-groups' && method === 'POST') {
        const body = JSON.parse(init?.body as string) as { name_ru: string; member_user_ids: string[] };
        const group = {
          group_id: 'group-1',
          name_ru: body.name_ru,
          created_by_user_id: 'instr-1',
          created_at: '2026-09-24T00:00:00Z',
          members: TRAINEES.items
            .filter((account) => body.member_user_ids.includes(account.id))
            .map((account) => ({ user_id: account.id, username: account.username, display_name_ru: account.display_name_ru })),
        };
        groups = [group];
        return jsonResponse(group, 201);
      }
      if (url === '/api/v1/trainee-groups/group-1' && method === 'DELETE') {
        groups = [];
        return new Response(null, { status: 204 });
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderCard();
    expect(await screen.findByText(ru.traineeGroupsEmpty)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.traineeGroupCreateButton }));
    await user.type(screen.getByLabelText(ru.traineeGroupNameLabel), 'Shift A');
    await user.click(await screen.findByLabelText('Trainee A'));
    await user.click(screen.getByLabelText('Trainee C'));
    await user.click(screen.getByRole('button', { name: ru.traineeGroupCreateButton }));

    expect(await screen.findByText('Shift A')).toBeInTheDocument();
    expect(screen.getByText(`${ru.traineeGroupMembersPrefix}: Trainee A, Trainee C`)).toBeInTheDocument();
    const createCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'POST');
    expect(JSON.parse((createCall![1] as RequestInit).body as string)).toEqual({
      name_ru: 'Shift A',
      member_user_ids: ['trainee-a', 'trainee-c'],
    });

    await user.click(screen.getByRole('button', { name: ru.traineeGroupDeleteButton }));
    await waitFor(() => expect(screen.getByText(ru.traineeGroupsEmpty)).toBeInTheDocument());
  });
});
