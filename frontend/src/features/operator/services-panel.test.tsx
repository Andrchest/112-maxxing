import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ServicesPanel } from './services-panel';
import { ru } from '@/shared/i18n/ru';
import { useCardStore } from '@/entities/card';
import { useStageStore } from '@/entities/stage';
import { makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function seed(selected: string[] = []): void {
  useCardStore.getState().setCard(makeCard({ values: { 'recipients.services': selected } }));
  useStageStore.setState({
    availableActions: [{ action_id: 'select_services', label_ru: 'Select services', permission: 'SELECT_SERVICES', trigger: null }],
  });
}

describe('ServicesPanel', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('issues selectRecipientService and renders the returned selection', async () => {
    const user = userEvent.setup();
    seed([]);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/services/select');
      expect(JSON.parse(init?.body as string)).toEqual({ service_type: 'FIRE_RESCUE' });
      return jsonResponse({
        card_id: 'card-1',
        selected_services: ['FIRE_RESCUE'],
        available_services: ['FIRE_RESCUE', 'POLICE', 'AMBULANCE', 'GAS_SERVICE', 'UTILITY_EMERGENCY', 'EDDS'],
        card: makeCard({ values: { 'recipients.services': ['FIRE_RESCUE'] } }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ServicesPanel sessionId="sess-1" />);
    const button = screen.getByRole('button', { name: ru.serviceTypeFireRescue });
    await user.click(button);

    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'));
    expect(useCardStore.getState().card?.values['recipients.services']).toEqual(['FIRE_RESCUE']);
  });

  it('issues deselectRecipientService for an already-selected service', async () => {
    const user = userEvent.setup();
    seed(['FIRE_RESCUE']);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/services/deselect');
      expect(JSON.parse(init?.body as string)).toEqual({ service_type: 'FIRE_RESCUE' });
      return jsonResponse({
        card_id: 'card-1',
        selected_services: [],
        available_services: ['FIRE_RESCUE'],
        card: makeCard({ values: { 'recipients.services': [] } }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ServicesPanel sessionId="sess-1" />);
    const button = screen.getByRole('button', { name: ru.serviceTypeFireRescue });
    expect(button).toHaveAttribute('aria-pressed', 'true');
    await user.click(button);

    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'false'));
  });

  it('disables the buttons when the server does not offer select_services', () => {
    useCardStore.getState().setCard(makeCard({ values: { 'recipients.services': [] } }));
    useStageStore.setState({ availableActions: [] });

    render(<ServicesPanel sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.serviceTypeFireRescue })).toBeDisabled();
  });
});
