import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from '@/shared/lib/api';
import { MLAuditPanel } from './ml-audit-panel';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/shared/lib/api')>(),
  apiFetch: vi.fn(),
}));

const response = {
  run_id: 'run-1', generated_at: '2026-09-29T19:00:00Z', evidence_method: 'attention_weights',
  earned_weight: 0.4, total_weight: 1,
  model: 'local-test', rubric_version: 'v1', score_percent: null, coverage_percent: 40,
  categories: [{ category: 'Безопасность', score_percent: 100 }],
  sources: [{ id: 'transcript:1', text: '🙂 Кровь есть?', kind: 'dialogue' }],
  results: [{
    criterion: { id: 'victims', category: 'Безопасность', question: 'Есть пострадавшие?', weight: 0.4 },
    passed: true, decision_token: 'да', awarded_weight: 0.4, issue: null,
    evidence: [{ source_id: 'transcript:1', start: 2, end: 13, quote: 'Кровь есть?' }],
  }],
};
let client: QueryClient;
function mount() {
  return render(<QueryClientProvider client={client}><MLAuditPanel sessionId="session-1" /></QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => client.clear());

describe('ML audit', () => {
  it('loads saved results on refresh and highlights Unicode source slices', async () => {
    vi.mocked(apiFetch).mockResolvedValue(response);
    mount();
    expect(await screen.findByText(/ML-балл: технически недоступен/)).toBeInTheDocument();
    expect(document.querySelector('mark')?.textContent).toBe('Кровь есть?');
    expect(apiFetch).toHaveBeenCalledWith('/reports/session-1/ml-audit');
    expect(apiFetch).toHaveBeenCalledTimes(1); // GET does not regenerate.
  });

  it('explicit regeneration saves and displays the new response', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(null).mockResolvedValue(response);
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Оценить с помощью ML' }));
    expect(await screen.findByText(/ML-балл: технически недоступен/)).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith('/reports/session-1/ml-audit?regenerate=true', { method: 'POST' });
  });

  it('shows transport failure without hiding the saved report', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(response).mockRejectedValue(new Error('offline'));
    mount();
    await screen.findByText(/ML-балл:/);
    fireEvent.click(screen.getByRole('button', { name: 'Оценить с помощью ML' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Основной отчёт не изменён');
    expect(screen.getByRole('button')).toBeEnabled();
    expect(screen.getByText(/ML-балл:/)).toBeInTheDocument();
  });

  it('does not present missing evidence as failure or success', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ...response, coverage_percent: 0,
      results: [{ ...response.results[0], passed: null, decision_token: null, awarded_weight: null, evidence: [], issue: 'provider_not_configured' }],
    });
    mount();
    expect(await screen.findByText(/Технический сбой/)).toBeInTheDocument();
    expect(screen.getByText(/Настройте локальную модель/)).toBeInTheDocument();
    expect(document.querySelector('mark')).toBeNull();
  });
});
