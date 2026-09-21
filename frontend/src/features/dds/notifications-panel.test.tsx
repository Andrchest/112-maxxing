import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NotificationsPanel } from './notifications-panel';
import { useNotificationStore } from '@/entities/notification';
import { ru } from '@/shared/i18n/ru';
import { makeNotification } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function renderPanel(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationsPanel sessionId={sessionId} />
    </QueryClientProvider>,
  );
}

describe('NotificationsPanel', () => {
  afterEach(() => {
    useNotificationStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('fetches listNotifications and renders the unacknowledged counter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/notifications');
        return jsonResponse({ items: [makeNotification(), makeNotification({ notification_id: 'n2', acknowledged_at_offset_ms: 500 })], total: 2 });
      }),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText(`${ru.ddsUnacknowledgedCountLabel}: 1`)).toBeInTheDocument());
    expect(screen.getAllByText('Fire spreading')[0]).toBeInTheDocument();
  });

  it('shows the empty state when there are no notifications', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0 })));
    renderPanel();
    expect(await screen.findByText(ru.ddsNotificationsEmpty)).toBeInTheDocument();
  });

  it('clicking acknowledge calls acknowledgeNotification and removes the button for that item', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/notifications')) {
          return jsonResponse({ items: [makeNotification()], total: 1 });
        }
        expect(url).toBe('/api/v1/sessions/sess-1/dds/notifications/notif-1/acknowledge');
        expect(init?.method).toBe('POST');
        return jsonResponse({ ...makeNotification(), acknowledged_at_offset_ms: 9000 });
      }),
    );

    renderPanel();
    const button = await screen.findByRole('button', { name: ru.ddsAcknowledgeNotificationButton });
    await user.click(button);

    await waitFor(() => expect(screen.queryByRole('button', { name: ru.ddsAcknowledgeNotificationButton })).not.toBeInTheDocument());
    expect(useNotificationStore.getState().items[0]?.acknowledged_at_offset_ms).toBe(9000);
  });
});
