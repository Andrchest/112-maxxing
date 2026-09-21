import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ExplanationPanel } from './explanation-panel';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ title: code, status, code }), { status, headers: { 'content-type': 'application/problem+json' } });
}

function renderPanel(props: {
  sessionId?: string;
  explanationAvailable?: boolean;
  currentScoreChecksum?: string;
  canManage?: boolean;
} = {}) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ExplanationPanel
        sessionId={props.sessionId ?? 'sess-1'}
        explanationAvailable={props.explanationAvailable ?? false}
        currentScoreChecksum={props.currentScoreChecksum ?? 'checksum-1'}
        canManage={props.canManage ?? false}
      />
    </QueryClientProvider>,
  );
}

describe('ExplanationPanel — deterministic-scores-only, generate/regenerate for INSTRUCTOR/ADMIN', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the "no explanation yet" state without fetching when explanation_available is false', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderPanel({ explanationAvailable: false });
    expect(screen.getByText(ru.reportExplanationNone)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('renders the disclaimer always, and no generate button for a trainee (canManage false)', () => {
    vi.stubGlobal('fetch', vi.fn());
    renderPanel({ explanationAvailable: false, canManage: false });
    expect(screen.getByText(ru.reportExplanationDisclaimer)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.reportExplanationGenerateButton })).not.toBeInTheDocument();
  });

  it('fetches and renders the explanation text when explanation_available is true', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          session_id: 'sess-1',
          audience: 'TRAINEE',
          text_ru: 'explanation body',
          generated_at: '2026-09-21T00:11:00Z',
          llm_provider: 'fake',
          llm_model: 'fake-llm',
          score_report_checksum: 'checksum-1',
        }),
      ),
    );
    renderPanel({ explanationAvailable: true, currentScoreChecksum: 'checksum-1' });
    expect(await screen.findByText('explanation body')).toBeInTheDocument();
  });

  it('renders the stale notice when the explanation checksum no longer matches the report', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          session_id: 'sess-1',
          audience: 'TRAINEE',
          text_ru: 'explanation body',
          generated_at: '2026-09-21T00:11:00Z',
          llm_provider: 'fake',
          llm_model: 'fake-llm',
          score_report_checksum: 'old-checksum',
        }),
      ),
    );
    renderPanel({ explanationAvailable: true, currentScoreChecksum: 'new-checksum' });
    expect(await screen.findByText(ru.reportExplanationStale)).toBeInTheDocument();
  });

  it('shows a generate button for INSTRUCTOR/ADMIN and posts a request on click', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        expect(String(input)).toBe('/api/v1/reports/sess-1/explanation');
        expect(JSON.parse(String(init.body))).toEqual({ regenerate: false, audience: 'TRAINEE' });
        return jsonResponse(
          {
            session_id: 'sess-1',
            audience: 'TRAINEE',
            text_ru: 'generated explanation',
            generated_at: '2026-09-21T00:11:00Z',
            llm_provider: 'fake',
            llm_model: 'fake-llm',
            score_report_checksum: 'checksum-1',
          },
          201,
        );
      }
      throw new Error('unexpected GET while explanation_available is false');
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPanel({ explanationAvailable: false, canManage: true });

    await user.click(screen.getByRole('button', { name: ru.reportExplanationGenerateButton }));

    expect(await screen.findByText('generated explanation')).toBeInTheDocument();
  });

  it('shows the model-unavailable message on a 503', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn(async () => problemResponse('LLM_UNAVAILABLE', 503)));

    renderPanel({ explanationAvailable: false, canManage: true });

    await user.click(screen.getByRole('button', { name: ru.reportExplanationGenerateButton }));

    await waitFor(() => expect(screen.getByText(ru.reportExplanationModelUnavailable)).toBeInTheDocument());
  });
});
