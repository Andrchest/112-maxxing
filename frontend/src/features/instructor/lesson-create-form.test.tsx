import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LessonCreateForm } from './lesson-create-form';
import { ru } from '@/shared/i18n/ru';
import type { LessonDetail } from '@/shared/api';

const SCENARIOS_RESPONSE = {
  items: [
    { scenario_id: 's1', slug: 'apartment-fire', title_ru: 'Fire test scenario', version_count: 1, latest_version: 1, latest_difficulty: 1 },
    { scenario_id: 's2', slug: 'ticket-05', title_ru: 'Hard ticket', version_count: 1, latest_version: 1, latest_difficulty: 4 },
  ],
  total: 2,
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
    group_id: null,
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
      if (url === '/api/v1/scenarios?limit=200' && method === 'GET') return jsonResponse(SCENARIOS_RESPONSE);
      if (url === '/api/v1/trainee-groups?limit=200' && method === 'GET') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') return jsonResponse(VERSIONS_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') return jsonResponse(TRAINEES_RESPONSE);
      if (url === '/api/v1/lessons' && method === 'POST') return jsonResponse(makeLesson(), 201);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();

    await user.type(screen.getByLabelText(ru.lessonFormTitleFieldLabel), 'Fire drill, three cards');

    const scenarioSelect = await screen.findByLabelText(ru.lessonFormEntryScenarioLabel);
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire test scenario` });
    await user.selectOptions(scenarioSelect, 's1');

    const versionSelect = await screen.findByLabelText(ru.lessonFormEntryVersionLabel);
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire scenario v1 (v1)` });
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

  it('sends a per-card timer override in session ms, only for the fields filled (I4 E31)', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios?limit=200' && method === 'GET') return jsonResponse(SCENARIOS_RESPONSE);
      if (url === '/api/v1/trainee-groups?limit=200' && method === 'GET') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') return jsonResponse(VERSIONS_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') return jsonResponse(TRAINEES_RESPONSE);
      if (url === '/api/v1/lessons' && method === 'POST') return jsonResponse(makeLesson(), 201);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();

    await user.type(screen.getByLabelText(ru.lessonFormTitleFieldLabel), 'Timers');
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire test scenario` });
    await user.selectOptions(screen.getByLabelText(ru.lessonFormEntryScenarioLabel), 's1');
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire scenario v1 (v1)` });
    await user.selectOptions(screen.getByLabelText(ru.lessonFormEntryVersionLabel), 'v1');
    const participantSelect = await screen.findByLabelText(`${ru.instructorParticipantUserIdLabel} — ${ru.roleTypeDds}`);
    await screen.findByRole('option', { name: 'Trainee One' });
    await user.selectOptions(participantSelect, 'trainee-1');

    const accept = screen.getByLabelText(ru.lessonFormEntryAcceptTimerLabel);
    const fill = screen.getByLabelText(ru.lessonFormEntryFillTimerLabel);
    expect(accept).toHaveValue(null);
    expect(accept).toHaveAttribute('placeholder', ru.lessonFormEntryTimerPlaceholder);
    await user.type(accept, '45');
    await user.type(fill, '0');
    expect(screen.getByRole('button', { name: ru.lessonFormCreateButton })).toBeDisabled();
    await user.clear(fill);

    await user.click(screen.getByRole('button', { name: ru.lessonFormCreateButton }));

    const createCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/lessons' && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    const body = JSON.parse(createCall[1].body as string);
    expect(body.scenario_plan[0].timers).toEqual({ accept_within_ms: 45_000 });
  });

  it('an entry switched to the picker has no phone: ON becomes OFF, is disabled, and is sent OFF (R41, D28)', async () => {
    // `street-rubbish-fire`'s shape since I4 E21: a memo scenario whose phone is ON by default.
    const phoneDefault = {
      items: [
        {
          ...VERSIONS_RESPONSE.items[0],
          variants: {
            supported: {
              card_source: ['GENERATED_CARD'],
              dds_mode: ['MEMO_STATUSES', 'RESOURCE_PICKER'],
              dds_card_check: ['OFF', 'ON'],
              dds_brigade_call: ['OFF', 'ON'],
            },
            default: { card_source: 'GENERATED_CARD', dds_mode: 'MEMO_STATUSES', dds_card_check: 'OFF', dds_brigade_call: 'ON' },
          },
        },
      ],
      total: 1,
    };
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios?limit=200' && method === 'GET') return jsonResponse(SCENARIOS_RESPONSE);
      if (url === '/api/v1/trainee-groups?limit=200' && method === 'GET') return jsonResponse({ items: [], total: 0 });
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') return jsonResponse(phoneDefault);
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') return jsonResponse(TRAINEES_RESPONSE);
      if (url === '/api/v1/lessons' && method === 'POST') return jsonResponse(makeLesson(), 201);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();
    await user.type(screen.getByLabelText(ru.lessonFormTitleFieldLabel), 'Picker drill');
    const scenarioSelect = await screen.findByLabelText(ru.lessonFormEntryScenarioLabel);
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire test scenario` });
    await user.selectOptions(scenarioSelect, 's1');
    const versionSelect = await screen.findByLabelText(ru.lessonFormEntryVersionLabel);
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 1 · Fire scenario v1 (v1)` });
    await user.selectOptions(versionSelect, 'v1');

    const phone = await screen.findByLabelText(ru.instructorVariantDdsBrigadeCallLabel);
    expect(phone).toHaveValue('ON');
    await user.selectOptions(screen.getByLabelText(ru.instructorVariantDdsModeLabel), 'RESOURCE_PICKER');
    expect(phone).toHaveValue('OFF');
    const suffix = ` — ${ru.instructorVariantUnavailableSuffix}`;
    expect(screen.getByRole('option', { name: `${ru.variantDdsBrigadeCallOn}${suffix}` })).toBeDisabled();

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
    expect(JSON.parse(createCall[1].body as string).scenario_plan[0].variants).toEqual({
      card_source: 'GENERATED_CARD',
      dds_mode: 'RESOURCE_PICKER',
      dds_card_check: 'OFF',
      dds_brigade_call: 'OFF',
    });
  });

  it('adding a second card offers AFTER_PREVIOUS_SESSION/AFTER_PREVIOUS_112_STAGE alongside AT_OFFSET', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/scenarios?limit=200') return jsonResponse(SCENARIOS_RESPONSE);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse({ items: [], total: 0 });
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
  it('a lesson for a group pre-fills its members and sends the ticked workstation of every card', async () => {
    const user = userEvent.setup();
    const trainees = {
      items: ['a', 'b', 'c'].map((suffix) => ({
        id: `trainee-${suffix}`,
        username: `trainee-${suffix}`,
        display_name_ru: `Trainee ${suffix.toUpperCase()}`,
        user_role: 'TRAINEE',
        created_at: '2026-09-21T00:00:00Z',
      })),
      total: 3,
    };
    const groups = {
      items: [
        {
          group_id: 'group-1',
          name_ru: 'Shift A',
          created_by_user_id: 'instr-1',
          created_at: '2026-09-21T00:00:00Z',
          members: trainees.items.map((account) => ({
            user_id: account.id,
            username: account.username,
            display_name_ru: account.display_name_ru,
          })),
        },
      ],
      total: 1,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios?limit=200') return jsonResponse(SCENARIOS_RESPONSE);
      if (url === '/api/v1/scenarios/s1/versions') return jsonResponse(VERSIONS_RESPONSE);
      if (url === '/api/v1/users?role=TRAINEE') return jsonResponse(trainees);
      if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse(groups);
      if (url === '/api/v1/lessons' && method === 'POST') return jsonResponse(makeLesson(), 201);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();
    await user.type(screen.getByLabelText(ru.lessonFormTitleFieldLabel), 'Group lesson');
    await screen.findByRole('option', { name: 'Shift A' });
    await user.selectOptions(screen.getByLabelText(ru.lessonFormGroupLabel), 'group-1');
    expect(screen.getByText(ru.lessonFormGroupHint)).toBeInTheDocument();

    // Three cards of the same version.
    await user.click(screen.getByRole('button', { name: ru.lessonFormEntryAddButton }));
    await user.click(screen.getByRole('button', { name: ru.lessonFormEntryAddButton }));
    const scenarioSelects = await screen.findAllByLabelText(ru.lessonFormEntryScenarioLabel);
    await screen.findAllByRole('option', { name: `${ru.difficultyLabel} 1 · Fire test scenario` });
    for (const [index, select] of scenarioSelects.entries()) {
      await user.selectOptions(select, 's1');
      const versionSelect = (await screen.findAllByLabelText(ru.lessonFormEntryVersionLabel))[index]!;
      await waitFor(() => expect(versionSelect).not.toBeDisabled());
      await screen.findAllByRole('option', { name: `${ru.difficultyLabel} 1 · Fire scenario v1 (v1)` });
      await user.selectOptions(versionSelect, 'v1');
    }

    // The matrix: one card each, then give card 3 to both B and C.
    expect(await screen.findByText(ru.lessonFormMatrixTitle)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: ru.lessonFormMatrixDistributeButton }));
    await user.click(screen.getByLabelText(`${ru.lessonFormEntryLabel} 3 — Trainee B`));

    // A card nobody is ticked for cannot be created.
    await user.click(screen.getByLabelText(`${ru.lessonFormEntryLabel} 1 — Trainee A`));
    expect(screen.getByText(ru.lessonFormMatrixEmptyEntry)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.lessonFormCreateButton })).toBeDisabled();
    await user.click(screen.getByLabelText(`${ru.lessonFormEntryLabel} 1 — Trainee A`));

    await user.click(screen.getByRole('button', { name: ru.lessonFormCreateButton }));
    const createCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/lessons' && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    const body = JSON.parse(createCall[1].body as string);
    expect(body.group_id).toBe('group-1');
    expect(body.participants).toEqual(
      trainees.items.map((account) => ({ user_id: account.id, assigned_role_type: 'DDS' })),
    );
    expect(body.scenario_plan.map((entry: { participants?: string[] }) => entry.participants)).toEqual([
      ['trainee-a'],
      ['trainee-b'],
      ['trainee-c', 'trainee-b'],
    ]);
  });

  it('filters the scenario picker by difficulty and shows the weight default', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === '/api/v1/scenarios?limit=200') return jsonResponse(SCENARIOS_RESPONSE);
        if (url === '/api/v1/users?role=TRAINEE') return jsonResponse(TRAINEES_RESPONSE);
        if (url === '/api/v1/trainee-groups?limit=200') return jsonResponse({ items: [], total: 0 });
        throw new Error(`unexpected fetch: ${url}`);
      }),
    );

    renderForm();
    await screen.findByRole('option', { name: `${ru.difficultyLabel} 4 · Hard ticket` });
    await user.selectOptions(screen.getByLabelText(ru.lessonFormDifficultyFilterLabel), '4');
    expect(screen.queryByRole('option', { name: `${ru.difficultyLabel} 1 · Fire test scenario` })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: `${ru.difficultyLabel} 4 · Hard ticket` })).toBeInTheDocument();
    expect(screen.getByText(ru.lessonFormEntryWeightHint)).toBeInTheDocument();
  });
});
