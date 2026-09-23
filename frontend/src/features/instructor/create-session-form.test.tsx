import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CreateSessionForm } from './create-session-form';
import { ru } from '@/shared/i18n/ru';
import type { HealthReadyResponse, SessionDetail } from '@/shared/api';

const HEALTH_READY_RESPONSE: HealthReadyResponse = {
  overall: 'READY',
  components: [
    { component: 'llm', status: 'READY', detail: null, checked_at: '2026-09-21T00:00:00Z' },
  ],
  required_components: ['llm'],
  require_inference_ready: true,
  model_profile: 'DEV_3060TI',
};

const SCENARIOS_RESPONSE = {
  items: [{ scenario_id: 's1', slug: 'apartment-fire', title_ru: 'Fire test scenario', version_count: 1, latest_version: 1 }],
  total: 1,
};

const TRAINEES_RESPONSE = {
  items: [
    { id: 'trainee-user-id-1', username: 'trainee1', display_name_ru: 'Trainee One', user_role: 'TRAINEE', created_at: '2026-09-21T00:00:00Z' },
  ],
  total: 1,
};

const VERSIONS_RESPONSE = {
  items: [
    {
      id: 'v1',
      scenario_id: 's1',
      schema_version: 1,
      version: 1,
      title: 'Fire scenario v1',
      description: 'test',
      difficulty: 1,
      role_chain: ['OPERATOR_112'],
      content_sha256: 'abc123',
      locked_at: null,
      created_at: '2026-09-21T00:00:00Z',
    },
  ],
  total: 1,
};

function makeSessionDetail(overrides: Partial<SessionDetail>): SessionDetail {
  return {
    id: 'sess-1',
    scenario_version_id: 'v1',
    scenario_slug: 'apartment-fire',
    scenario_version: 1,
    session_mode: 'SINGLE_ROLE',
    state: 'READY',
    session_seed: 'seed-1',
    time_scale: 1,
    incident_id: 'inc-1',
    role_chain: ['OPERATOR_112'],
    stages: [],
    active_role_stage_id: null,
    participants: [],
    created_by_user_id: 'instr-1',
    created_at: '2026-09-21T00:00:00Z',
    started_at: null,
    completed_at: null,
    abort_reason: null,
    monotonic_offset_ms: 0,
    last_seq_no: 0,
    transition_pause_seconds: 0,
    transition_continue_available_at_offset_ms: null,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200, contentType = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': contentType } });
}

function renderForm() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <CreateSessionForm />
    </QueryClientProvider>,
  );
}

async function fillInScenarioVersionAndParticipant(user: ReturnType<typeof userEvent.setup>) {
  const scenarioSelect = await screen.findByLabelText(ru.instructorScenarioLabel);
  await screen.findByRole('option', { name: 'Fire test scenario' });
  await user.selectOptions(scenarioSelect, 's1');

  const versionSelect = await screen.findByLabelText(ru.instructorVersionLabel);
  await screen.findByRole('option', { name: 'Fire scenario v1 (v1)' });
  await user.selectOptions(versionSelect, 'v1');

  const participantSelect = await screen.findByLabelText(
    `${ru.instructorParticipantUserIdLabel} — ${ru.roleTypeOperator112}`,
  );
  await screen.findByRole('option', { name: 'Trainee One' });
  await user.selectOptions(participantSelect, 'trainee-user-id-1');
}

describe('CreateSessionForm', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues exactly the documented createSession and startSession requests', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios' && method === 'GET') {
        return jsonResponse(SCENARIOS_RESPONSE);
      }
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') {
        return jsonResponse(VERSIONS_RESPONSE);
      }
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') {
        return jsonResponse(TRAINEES_RESPONSE);
      }
      if (url === '/api/v1/health/ready' && method === 'GET') {
        return jsonResponse(HEALTH_READY_RESPONSE);
      }
      if (url === '/api/v1/sessions' && method === 'POST') {
        return jsonResponse(makeSessionDetail({ state: 'READY' }), 201);
      }
      if (url === '/api/v1/sessions/sess-1/start' && method === 'POST') {
        return jsonResponse(makeSessionDetail({ state: 'ACTIVE' }), 200);
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();
    await fillInScenarioVersionAndParticipant(user);

    await user.click(screen.getByRole('button', { name: ru.instructorCreateButton }));

    const createCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/sessions' && (init as RequestInit | undefined)?.method === 'POST',
      );
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    const [, createInit] = createCall;
    expect(JSON.parse(createInit.body as string)).toEqual({
      scenario_version_id: 'v1',
      session_mode: 'SINGLE_ROLE',
      participants: [{ user_id: 'trainee-user-id-1', assigned_role_type: 'OPERATOR_112' }],
      time_scale: 1,
    });

    await screen.findByText(`${ru.instructorSessionStateLabel}: ${ru.sessionStateReady}`);
    await waitFor(() => expect(screen.getByRole('button', { name: ru.instructorStartButton })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: ru.instructorStartButton }));

    const startCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/sessions/sess-1/start' && (init as RequestInit)?.method === 'POST',
      );
      expect(call).toBeDefined();
      return call as [string, RequestInit];
    });
    expect(startCall[1].body).toBeUndefined();

    await screen.findByText(`${ru.instructorSessionStateLabel}: ${ru.sessionStateActive}`);
  });

  it('renders the Russian INFERENCE_NOT_READY message when start is refused', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios' && method === 'GET') {
        return jsonResponse(SCENARIOS_RESPONSE);
      }
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') {
        return jsonResponse(VERSIONS_RESPONSE);
      }
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') {
        return jsonResponse(TRAINEES_RESPONSE);
      }
      if (url === '/api/v1/health/ready' && method === 'GET') {
        return jsonResponse(HEALTH_READY_RESPONSE);
      }
      if (url === '/api/v1/sessions' && method === 'POST') {
        return jsonResponse(makeSessionDetail({ state: 'READY' }), 201);
      }
      if (url === '/api/v1/sessions/sess-1/start' && method === 'POST') {
        return jsonResponse(
          { title: 'Service Unavailable', status: 503, code: 'INFERENCE_NOT_READY' },
          503,
          'application/problem+json',
        );
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderForm();
    await fillInScenarioVersionAndParticipant(user);
    await user.click(screen.getByRole('button', { name: ru.instructorCreateButton }));
    await screen.findByText(`${ru.instructorSessionStateLabel}: ${ru.sessionStateReady}`);
    await waitFor(() => expect(screen.getByRole('button', { name: ru.instructorStartButton })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: ru.instructorStartButton }));

    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemInferenceNotReady);
  });

  // -- R9 (SPEC §37): Start button gated on inference readiness -------------------------------

  function fetchMockWithHealth(health: HealthReadyResponse) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/scenarios' && method === 'GET') {
        return jsonResponse(SCENARIOS_RESPONSE);
      }
      if (url === '/api/v1/scenarios/s1/versions' && method === 'GET') {
        return jsonResponse(VERSIONS_RESPONSE);
      }
      if (url === '/api/v1/users?role=TRAINEE' && method === 'GET') {
        return jsonResponse(TRAINEES_RESPONSE);
      }
      if (url === '/api/v1/health/ready' && method === 'GET') {
        return jsonResponse(health);
      }
      if (url === '/api/v1/sessions' && method === 'POST') {
        return jsonResponse(makeSessionDetail({ state: 'READY' }), 201);
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
  }

  async function createUpToReadySession(user: ReturnType<typeof userEvent.setup>) {
    await fillInScenarioVersionAndParticipant(user);
    await user.click(screen.getByRole('button', { name: ru.instructorCreateButton }));
    await screen.findByText(`${ru.instructorSessionStateLabel}: ${ru.sessionStateReady}`);
  }

  it.each(['NOT_READY', 'WARMING', 'FATAL'] as const)(
    'disables Start with the Russian reason when overall is %s',
    async (overall) => {
      const user = userEvent.setup();
      vi.stubGlobal(
        'fetch',
        fetchMockWithHealth({
          ...HEALTH_READY_RESPONSE,
          overall,
          components: [{ component: 'llm', status: overall, detail: null, checked_at: '2026-09-21T00:00:00Z' }],
        }),
      );

      renderForm();
      await createUpToReadySession(user);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: ru.instructorStartButton })).toBeDisabled();
      });
      expect(await screen.findByText(ru.instructorStartNotReadyReason, { exact: false })).toBeInTheDocument();
    },
  );

  it('enables Start when overall is READY', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', fetchMockWithHealth(HEALTH_READY_RESPONSE));

    renderForm();
    await createUpToReadySession(user);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: ru.instructorStartButton })).toBeEnabled();
    });
    expect(screen.queryByText(ru.instructorStartNotReadyReason, { exact: false })).not.toBeInTheDocument();
  });

  it('enables Start when readiness is not required even though overall is not READY', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      fetchMockWithHealth({ ...HEALTH_READY_RESPONSE, overall: 'NOT_READY', require_inference_ready: false }),
    );

    renderForm();
    await createUpToReadySession(user);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: ru.instructorStartButton })).toBeEnabled();
    });
  });
});
