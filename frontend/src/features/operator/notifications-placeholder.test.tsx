import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NotificationsPlaceholder } from './notifications-placeholder';
import { useNotificationStore } from '@/entities/notification';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function makeNotification(overrides: Record<string, unknown> = {}) {
  return {
    notification_id: 'notif-1',
    incident_id: 'inc-1',
    audience_role: 'OPERATOR_112',
    severity: 'WARNING',
    title_ru: 'Repeat call',
    body_ru: 'The caller called back.',
    created_at_offset_ms: 1000,
    source_world_event_id: null,
    acknowledged_at_offset_ms: null,
    ...overrides,
  };
}

function renderPanel(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationsPlaceholder sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('NotificationsPlaceholder (Operator 112 real panel, E10)', () => {
  afterEach(() => {
    useNotificationStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('fetches listNotifications and renders the unacknowledged counter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/notifications');
        return jsonResponse({ items: [makeNotification()], total: 1 });
      }),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText(`${ru.ddsUnacknowledgedCountLabel}: 1`)).toBeInTheDocument());
  });

  it('clicking acknowledge calls acknowledgeNotification', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/notifications')) return jsonResponse({ items: [makeNotification()], total: 1 });
        expect(url).toBe('/api/v1/sessions/sess-1/dds/notifications/notif-1/acknowledge');
        return jsonResponse({ ...makeNotification(), acknowledged_at_offset_ms: 5000 });
      }),
    );

    renderPanel();
    const button = await screen.findByRole('button', { name: ru.ddsAcknowledgeNotificationButton });
    await user.click(button);

    await waitFor(() => expect(useNotificationStore.getState().items[0]?.acknowledged_at_offset_ms).toBe(5000));
  });
});
