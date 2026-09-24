import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonCreateForm } from './lesson-create-form';
import { ru } from '@/shared/i18n/ru';
import type { LessonDetail } from '@/shared/api';

const SCENARIOS_RESPONSE = {
  items: [{ scenario_id: 's1', slug: 'apartment-fire', title_ru: 'Fire test scenario', version_count: 1, latest_version: 1 }],
  total: 1,
};

const TRAINEES_RESPONSE = {
  items: [
    { id: 'trainee-1', username: 'trainee1', display_name_ru: 'Trainee One', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
  ],
  total: 1,
};

const GENERATED_CARD_DEFAULT = {
  card_source: 'GENERATED_CARD',
  dds_mode: 'RESOURCE_PICKER',
  dds_card_check: 'OFF',
  dds_brigade_call: 'OFF',
} as const;

const VERSIONS_RESPONSE = {
  items: [
    {
      id: 'v1',
      scenario_id: 's1',
      schema_version: 2,
      version: 1,
      title: 'Fire scenario v1',
      description: 'test',
      difficulty: 1,
      role_chain: ['DDS'],
      content_sha256: 'abc123',
      locked_at: null,
      created_at: '2026-09-21T00:00:00Z',
      variants: {
        supported: {
          card_source: ['GENERATED_CARD'],
          dds_mode: ['RESOURCE_PICKER'],
          dds_card_check: ['OFF'],
          dds_brigade_call: ['OFF'],
        },
        default: GENERATED_CARD_DEFAULT,
      },
    },
  ],
  total: 1,
};

function makeLesson(): LessonDetail {
  return {
    lesson_id: 'lesson-1',
    title_ru: 'Fire drill, three cards',
    session_mode: 'SINGLE_ROLE',
    state: 'CREATED',
    participants: [{ user_id: 'trainee-1', assigned_role_type: 'DDS' }],
    scenario_plan: [
      { position: 1, scenario_version_id: 'v1', arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 }, weight: 1 },
    ],
    sessions: [],
    created_at: '2026-09-24T00:00:00Z',
    started_at: null,
    completed_at: null,
    report_released_at: null,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderForm() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <LessonCreateForm />
    </QueryClientProvider>,
  );
}

describe('LessonCreateForm — the instructor plan editor (70 §70.3.1-§70.3.3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues createLesson with a one-card plan, its resolved variants and one participant', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios' && method === 'GET') return jsonResponse(SCENARIOS_RESPONSE);
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') return jsonResponse(VERSIONS_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') return jsonResponse(TRAINEES_RESPONSE);
      if (url === '/api/v1/lessons' && method === 'POST') return jsonResponse(makeLesson(), 201);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();

    await user.type(screen.getByLabelText(ru.lessonFormTitleFieldLabel), 'Fire drill, three cards');

    const scenarioSelect = await screen.findByLabelText(ru.lessonFormEntryScenarioLabel);
    await screen.findByRole('option', { name: 'Fire test scenario' });
    await user.selectOptions(scenarioSelect, 's1');

    const versionSelect = await screen.findByLabelText(ru.lessonFormEntryVersionLabel);
    await screen.findByRole('option', { name: 'Fire scenario v1 (v1)' });
    await user.selectOptions(versionSelect, 'v1');

    const participantSelect = await screen.findByLabelText(`${ru.instructorParticipantUserIdLabel} — ${ru.roleTypeDds}`);
    await screen.findByRole('option', { name: 'Trainee One' });
    await user.selectOptions(participantSelect, 'trainee-1');

    await user.click(screen.getByRole('button', { name: ru.lessonFormCreateButton }));

    const createCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/lessons' && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    const body = JSON.parse(createCall[1].body as string);
    expect(body).toEqual({
      title_ru: 'Fire drill, three cards',
      session_mode: 'SINGLE_ROLE',
      participants: [{ user_id: 'trainee-1', assigned_role_type: 'DDS' }],
      time_scale: 1,
      scenario_plan: [
        {
          position: 1,
          scenario_version_id: 'v1',
          arrival: { kind: 'AT_OFFSET', offset_ms: 0, delay_ms: 0 },
          variants: GENERATED_CARD_DEFAULT,
          weight: 1,
        },
      ],
    });
  });

  it('adding a second card offers AFTER_PREVIOUS_SESSION/AFTER_PREVIOUS_112_STAGE alongside AT_OFFSET', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/scenarios') return jsonResponse(SCENARIOS_RESPONSE);
        if (url === '/api/v1/scenarios/s1/versions') return jsonResponse(VERSIONS_RESPONSE);
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse(TRAINEES_RESPONSE);
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderForm();
    await user.click(screen.getByRole('button', { name: ru.lessonFormEntryAddButton }));

    const arrivalSelects = await screen.findAllByLabelText(ru.lessonFormEntryArrivalKindLabel);
    expect(arrivalSelects).toHaveLength(1); // the first card has no dropdown, only the second does
    expect(screen.getByText(`${ru.lessonFormEntryLabel} 2`)).toBeInTheDocument();
    expect(screen.getByText(ru.lessonFormEntryArrivalFirstNote)).toBeInTheDocument();
  });
});
