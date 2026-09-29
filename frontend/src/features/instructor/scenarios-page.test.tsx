import { render, screen, waitFor, within } from '@testing-library/react';
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
    // I7 E53 (G19): the rule's Russian template is shown; the English detail stays as the title.
    const issue = screen.getByText(new RegExp(ru.scenarioIssueR18.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    expect(issue).toHaveAttribute('title', 'unknown role');
    expect(screen.queryByText(/unknown role/)).not.toBeInTheDocument();
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

  it('the show-archived checkbox refetches with include_archived and shows the archived scenario', async () => {
    const user = userEvent.setup();
    signIn();
    const archived = { ...SCENARIOS_RESPONSE.items[0], scenario_id: 's2', slug: 'old', title_ru: 'Archived scenario', archived_at: '2026-09-25T00:00:00Z' };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes('include_archived=true')) {
        return jsonResponse({ items: [...SCENARIOS_RESPONSE.items, archived], total: 2 });
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText('Fire test scenario');
    expect(screen.queryByText('Archived scenario')).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(ru.scenarioShowArchivedLabel));

    expect(await screen.findByText('Archived scenario')).toBeInTheDocument();
    expect(screen.getByText(ru.scenarioArchivedBadge)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.scenarioUnarchiveButton })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('include_archived=true'), expect.anything());
  });

  // I7 E53 (G13): «Категория событий» — several categories at once, and «Без категории».
  it('filters the scenario list by event category', async () => {
    const user = userEvent.setup();
    signIn();
    const items = [
      { ...SCENARIOS_RESPONSE.items[0], category: { group_no: 1, name_ru: 'Fire group' } },
      { ...SCENARIOS_RESPONSE.items[0], scenario_id: 's2', slug: 'crash', title_ru: 'Crash scenario', category: { group_no: 2, name_ru: 'Road group' } },
      { ...SCENARIOS_RESPONSE.items[0], scenario_id: 's3', slug: 'plain', title_ru: 'Plain scenario', category: null },
    ];
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items, total: 3 })));
    renderPage();
    await screen.findByText('Crash scenario');

    const group = screen.getByRole('group', { name: ru.scenarioCategoryFilterLabel });
    await user.click(within(group).getByRole('button', { name: 'Road group' }));
    expect(screen.queryByText('Fire test scenario')).not.toBeInTheDocument();
    expect(screen.getByText('Crash scenario')).toBeInTheDocument();

    await user.click(within(group).getByRole('button', { name: 'Fire group' }));
    expect(screen.getByText('Fire test scenario')).toBeInTheDocument();
    expect(screen.queryByText('Plain scenario')).not.toBeInTheDocument();

    await user.click(within(group).getByRole('button', { name: ru.scenarioCategoryAll }));
    expect(screen.getByText('Plain scenario')).toBeInTheDocument();
  });

  // I7 E53 (G14a): «Скачать» per version — YAML by default, JSON on request.
  it('downloads a version as YAML or JSON', async () => {
    const user = userEvent.setup();
    signIn();
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    const createObjectURL = vi.fn(() => 'blob:scenario');
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/scenarios/s1/versions')) {
        return jsonResponse({ items: [{ id: 'ver-1', scenario_id: 's1', version: 1 }], total: 1 });
      }
      if (url.includes('/document')) {
        return new Response('slug: apartment-fire\n', { status: 200, headers: { 'content-type': 'application/yaml' } });
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    try {
      renderPage();
      await screen.findByText('Fire test scenario');

      await user.click(screen.getByRole('button', { name: ru.scenarioVersionsButton }));
      await user.click(await screen.findByRole('button', { name: ru.scenarioDownloadButton }));
      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/scenarios/versions/ver-1/document', expect.anything()),
      );

      await user.click(screen.getByRole('button', { name: ru.scenarioDownloadJsonButton }));
      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/scenarios/versions/ver-1/document?format=json', expect.anything()),
      );
      await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
      expect(createObjectURL).toHaveBeenCalledTimes(2);
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
      click.mockRestore();
    }
  });

  // I7 E46c (owner item 6): several files at once import one after another; one bad file never
  // stops the rest, and the summary line counts only the ones that made it in.
  it('imports several files at once, one bad file does not stop the rest', async () => {
    const user = userEvent.setup();
    signIn();
    const scenarioVersion = (version: number) => ({
      id: `v${version}`,
      scenario_id: 's1',
      schema_version: 2,
      version,
      title: 'x',
      description: '',
      difficulty: 1,
      role_chain: [],
      content_sha256: 'abc',
      created_at: '2026-09-21T00:00:00Z',
      variants: {
        supported: { card_source: ['GENERATED_CARD'], dds_mode: ['RESOURCE_PICKER'], dds_card_check: ['OFF'], dds_brigade_call: ['OFF'] },
        default: { card_source: 'GENERATED_CARD', dds_mode: 'RESOURCE_PICKER', dds_card_check: 'OFF', dds_brigade_call: 'OFF' },
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST' && String(input).endsWith('/scenarios/import')) {
        const body = JSON.parse(String(init.body));
        if (body.source_path === 'bad.json') {
          return new Response(
            JSON.stringify({ type: 'about:blank', title: 'x', status: 422, code: 'MATERIAL_TYPE_NOT_ALLOWED' }),
            { status: 422, headers: { 'content-type': 'application/problem+json' } },
          );
        }
        return jsonResponse(scenarioVersion(1), 201);
      }
      return jsonResponse(SCENARIOS_RESPONSE);
    });
    vi.stubGlobal('fetch', fetchMock);
    renderPage();
    await screen.findByText('Fire test scenario');

    const input = screen.getByLabelText(ru.scenarioUploadFieldLabel) as HTMLInputElement;
    await user.upload(input, [makeFile('first.json', '{"slug":"a"}'), makeFile('bad.json', '{"slug":"b"}'), makeFile('third.json', '{"slug":"c"}')]);

    await user.click(await screen.findByRole('button', { name: ru.scenarioBatchImportButton }));

    const summary = ru.uploadBatchSummaryRu.replace('{done}', '2').replace('{total}', '3');
    expect(await screen.findByText(summary)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`bad\\.json.*${ru.uploadBatchErrorPrefixRu}`))).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(ru.uploadBatchUploadedRu))).toHaveLength(2);
  });

  // I7 E53 (G19): a rule number without a Russian template keeps the server's English text.
  it('keeps the English message for a rule number without a Russian template', async () => {
    const user = userEvent.setup();
    signIn();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'POST' && String(input).endsWith('/scenarios/validate')) {
          return jsonResponse({ valid: false, issues: [{ rule_number: 99, severity: 'ERROR', location: 'x', message: 'future rule text' }], checked_rule_count: 44 });
        }
        return jsonResponse(SCENARIOS_RESPONSE);
      }),
    );
    renderPage();
    await screen.findByText('Fire test scenario');

    await user.upload(screen.getByLabelText(ru.scenarioUploadFieldLabel) as HTMLInputElement, makeFile('bad.yaml', 'x: 1'));
    await waitFor(() => expect(screen.getByRole('button', { name: ru.scenarioUploadValidateButton })).not.toBeDisabled());
    await user.click(screen.getByRole('button', { name: ru.scenarioUploadValidateButton }));

    expect(await screen.findByText(/future rule text/)).toBeInTheDocument();
  });
});
