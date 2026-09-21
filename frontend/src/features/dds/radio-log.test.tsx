import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RadioLog } from './radio-log';
import { useRadioStore } from '@/entities/radio';
import { ru } from '@/shared/i18n/ru';
import { makeRadioMessage } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderLog(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <RadioLog sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('RadioLog', () => {
  afterEach(() => {
    useRadioStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('fetches listRadioMessages and renders messages in log order', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/radio-messages');
        return jsonResponse({
          items: [makeRadioMessage({ radio_message_id: 'r1', seq_no: 1, text_ru: 'Departed.' }), makeRadioMessage({ radio_message_id: 'r2', seq_no: 2, text_ru: 'Arrived.' })],
          last_seq_no: 2,
        });
      }),
    );

    renderLog();

    await waitFor(() => expect(screen.getByText('Departed.')).toBeInTheDocument());
    const items = screen.getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Departed.');
    expect(items[1]).toHaveTextContent('Arrived.');
  });

  it('shows the empty state when there are no messages', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0 })));
    renderLog();
    expect(await screen.findByText(ru.ddsRadioLogEmpty)).toBeInTheDocument();
  });
});
