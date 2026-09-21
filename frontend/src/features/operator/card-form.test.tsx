import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CardForm } from './card-form';
import { useCardStore } from '@/entities/card';
import { useStageStore } from '@/entities/stage';
import { useSessionEventsStore } from '@/entities/session';
import { makeCard } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function seedEditable(cardOverrides: Parameters<typeof makeCard>[0] = {}): void {
  useCardStore.getState().setCard(makeCard(cardOverrides));
  useStageStore.setState({
    availableActions: [{ action_id: 'edit_card', label_ru: 'Edit card', permission: 'EDIT_CARD', trigger: null }],
  });
}

describe('CardForm — one setCardField command per field commit (DESIGN 2)', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    useSessionEventsStore.getState().reset('sess-1', 0);
    vi.unstubAllGlobals();
  });

  it('commits address.house on blur with the exact documented body', async () => {
    const user = userEvent.setup();
    seedEditable();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/card/field');
      expect(init?.method).toBe('PUT');
      const body = JSON.parse(init?.body as string);
      expect(body.field_path).toBe('address.house');
      expect(body.new_value).toBe('72');
      expect(typeof body.client_command_id).toBe('string');
      return jsonResponse({
        card: makeCard({ values: { 'address.house': '72' }, revision_counter: 1 }),
        revision: {
          revision_id: 'rev-1',
          card_id: 'card-1',
          revision_no: 1,
          field_path: 'address.house',
          previous_value: null,
          new_value: '72',
          actor: { actor_type: 'TRAINEE', actor_id: 'u1' },
          at_offset_ms: 0,
        },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<CardForm sessionId="sess-1" />);
    const input = screen.getByLabelText('address.house');
    await user.click(input);
    await user.type(input, '72');
    await user.tab();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(useCardStore.getState().card?.values['address.house']).toBe('72'));
  });

  it('issues no request when blurring without changing the value', async () => {
    const user = userEvent.setup();
    seedEditable({ values: { 'address.house': '72' } });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<CardForm sessionId="sess-1" />);
    const input = screen.getByLabelText('address.house');
    await user.click(input);
    await user.tab();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('restores the confirmed value and shows the problem message when the command fails', async () => {
    const user = userEvent.setup();
    seedEditable({ values: { 'address.house': '27' } });
    const fetchMock = vi.fn(async () =>
      jsonResponse({ title: 'Unprocessable', status: 422, code: 'CARD_VALUE_TYPE_MISMATCH' }, 422),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(<CardForm sessionId="sess-1" />);
    const input = screen.getByLabelText<HTMLInputElement>('address.house');
    await user.clear(input);
    await user.type(input, '72');
    await user.tab();

    await screen.findByRole('alert');
    await waitFor(() => expect(input.value).toBe('27'));
    expect(useCardStore.getState().card?.values['address.house']).toBe('27');
  });

  it('never fills a field from ASR_FINAL events (DESIGN 2 structural guarantee)', async () => {
    seedEditable({ values: { 'description.text': '' } });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    render(<CardForm sessionId="sess-1" />);

    // `act` flushes any effect the event triggers (not just the synchronous store update) before
    // the assertions below — otherwise a sabotaged effect-based autofill would race the assertion
    // and this test would pass by accident.
    await act(async () => {
      useSessionEventsStore.getState().applyEvent({
        seq_no: 1,
        event_type: 'ASR_FINAL',
        timestamp_utc: '2026-09-21T10:00:00.000Z',
        monotonic_offset_ms: 1000,
        payload: { call_id: 'call-1', turn_index: 0, text: 'fire at 5 Lenina street' },
      });
    });

    const descriptionInput = screen.getByLabelText<HTMLInputElement>('description.text');
    expect(descriptionInput.value).toBe('');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useCardStore.getState().card?.values['description.text']).toBe('');
  });

  it('excludes recipients.services from the generic field renderer (owned by the services panel)', () => {
    seedEditable();
    render(<CardForm sessionId="sess-1" />);
    expect(screen.queryByLabelText('recipients.services')).not.toBeInTheDocument();
  });

  it('disables every field when the server does not offer edit_card', () => {
    useCardStore.getState().setCard(makeCard({ values: { 'address.house': '27' } }));
    useStageStore.setState({ availableActions: [] });

    render(<CardForm sessionId="sess-1" />);
    expect(screen.getByLabelText<HTMLInputElement>('address.house').disabled).toBe(true);
  });
});
