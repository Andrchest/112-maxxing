import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DdsHeaderStrip } from './dds-header-strip';
import { makeWorkItem } from './test-fixtures';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function renderStrip(sessionId: string, workItem: ReturnType<typeof makeWorkItem>) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <DdsHeaderStrip sessionId={sessionId} workItem={workItem} />
    </QueryClientProvider>,
  );
}

// I3 E5c (manager review): the reference's phone-row header strip, read-only, no fill timer (the
// ДДС has none — only the 112 operator does).
describe('DdsHeaderStrip — phone rows and the card number, no fill timer', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the header-group fields and the display_number, never a timer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          items: [{ session_id: 'sess-1', incident_id: 'inc-1', display_number: 36814851, lesson_id: null, card_status: 'REGISTERED', session_state: 'ACTIVE', arrived_at_utc: '2026-09-24T11:13:19Z', session_offset_ms: 1000, accept_deadline_offset_ms: null, fill_deadline_offset_ms: null, not_completed_deadline_offset_ms: null, classifier_code: null, address_line_ru: 'Test City', my_role_type: 'DDS' }],
          total: 1,
        }),
      ),
    );
    const workItem = makeWorkItem({
      field_specs: [
        { field_path: 'caller.phone_aon', value_type: 'STRING', enum_name: null, label_ru: 'AON', scoring_relevant: false, required_for_handoff: false, group: 'header' },
      ],
      card_values: { 'caller.phone_aon': '+79161234567' },
    });
    renderStrip('sess-1', workItem);

    expect(screen.getByText(/\+79161234567/)).toBeInTheDocument();
    expect(await screen.findByText(/36814851/)).toBeInTheDocument();
    expect(screen.queryByTestId('card-fill-timer')).not.toBeInTheDocument();
  });

  it('renders nothing when there is no header data and no resolvable number', () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    const { container } = renderStrip('sess-1', makeWorkItem({ field_specs: [], card_values: {} }));
    expect(container).toBeEmptyDOMElement();
  });
});
