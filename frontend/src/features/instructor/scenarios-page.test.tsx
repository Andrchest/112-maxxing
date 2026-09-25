import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScenariosPage } from './scenarios-page';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function signIn(): void {
  useAuthStore.setState({
    token: 'jwt-token',
    isAuthenticated: true,
    user: { id: 'instr-1', username: 'instructor', display_name_ru: 'Instructor', user_role: 'INSTRUCTOR', created_at: '2026-09-21T00:00:00Z' },
  });
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/instructor/scenarios']}>
        <ScenariosPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const SCENARIOS_RESPONSE = {
  items: [
    { scenario_id: 's1', slug: 'apartment-fire', title_ru: 'Fire test scenario', version_count: 1, latest_version: 1, latest_difficulty: 1, archived_at: null },
  ],
  total: 1,
};

function makeFile(name: string, content: string): File {
  return new File([content], name, { type: 'text/plain' });
}

// I4 E32 (HLD 71 §71.9): the «Сценарии» upload page (ТЗ ¶222, ¶229).
describe('ScenariosPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
  });

  it('lists scenarios and shows the archive action', async () => {
    signIn();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(SCENARIOS_RESPONSE)));
    renderPage();
    expect(await screen.findByText('Fire test scenario')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.scenarioArchiveButton })).toBeInTheDocument();
  });

  it('validate shows the issues in the body, always 200 (never an error status)', async () => {
    const user = userEvent.setup();
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' && String(input).endsWith('/scenarios/validate')) {
        const body = JSON.parse(String(init.body));
        expect(body.format).toBe('YAML');
        return jsonResponse({ valid: false, issues: [{ rule_number: 18, severity: 'ERROR', location: 'role_chain', message: 'unknown role' }], checked_rule_count: 40 });
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText('Fire test scenario');

    const input = screen.getByLabelText(ru.scenarioUploadFieldLabel) as HTMLInputElement;
    await user.upload(input, makeFile('bad.yaml', 'role_chain: [EDDS]'));

    await waitFor(() => expect(screen.getByRole('button', { name: ru.scenarioUploadValidateButton })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: ru.scenarioUploadValidateButton }));

    expect(await screen.findByText(ru.scenarioUploadInvalidRu)).toBeInTheDocument();
    expect(screen.getByText(/unknown role/)).toBeInTheDocument();
  });

  it('import posts the file content with the extension-derived format', async () => {
    const user = userEvent.setup();
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' && String(input).endsWith('/scenarios/import')) {
        const body = JSON.parse(String(init.body));
        expect(body.format).toBe('JSON');
        expect(body.content).toBe('{"slug":"x"}');
        return jsonResponse({ id: 'v1', scenario_id: 's1', schema_version: 2, version: 1, title: 'x', description: '', difficulty: 1, role_chain: [], content_sha256: 'abc', created_at: '2026-09-21T00:00:00Z', variants: { supported: { card_source: ['GENERATED_CARD'], dds_mode: ['RESOURCE_PICKER'], dds_card_check: ['OFF'], dds_brigade_call: ['OFF'] }, default: { card_source: 'GENERATED_CARD', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' } } }, 201);
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText('Fire test scenario');

    const input = screen.getByLabelText(ru.scenarioUploadFieldLabel) as HTMLInputElement;
    await user.upload(input, makeFile('scenario.json', '{"slug":"x"}'));

    await waitFor(() => expect(screen.getByRole('button', { name: ru.scenarioUploadImportButton })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: ru.scenarioUploadImportButton }));

    expect(await screen.findByText(ru.scenarioUploadImportedRu)).toBeInTheDocument();
  });

  it('archiving a scenario calls archiveScenario', async () => {
    const user = userEvent.setup();
    signIn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' && String(input).endsWith('/archive')) {
        return jsonResponse({ ...SCENARIOS_RESPONSE.items[0], archived_at: '2026-09-25T00:00:00Z' });
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText('Fire test scenario');

    await user.click(screen.getByRole('button', { name: ru.scenarioArchiveButton }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/scenarios/s1/archive', expect.objectContaining({ method: 'POST' })));
  });
});
