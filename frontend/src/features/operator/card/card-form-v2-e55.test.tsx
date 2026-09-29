// I7 E55 (G16): the card-instruction fields on the v2 card — the six caller statuses, the
// channel select, the injured count that appears once the casualties toggle is on, the 103 block's
// refusal toggle, and the description's 1999-character cap with the reference's counter. Every
// commit is still exactly one `setCardField` (D12).
//
// Label text comes from `./test-fixtures.ts` (`E55_LABELS`) — the no-Cyrillic guard scans this
// `.tsx` file too.
import { render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CardForm } from '../card-form';
import { useCardStore } from '@/entities/card';
import type { OperatorCardView } from '@/entities/card';
import { useStageStore } from '@/entities/stage';
import { ru } from '@/shared/i18n/ru';
import { E55_LABELS, makeE55Card } from './test-fixtures';

function renderCardForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CardForm sessionId="sess-1" monotonicOffsetMs={0} />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function isBackgroundReadUrl(url: string): boolean {
  return url.includes('/events') || url.includes('/incidents');
}

function seedEditable(overrides: Partial<OperatorCardView> = {}): void {
  useCardStore.getState().setCard(makeE55Card(overrides));
  useStageStore.setState({
    availableActions: [{ action_id: 'edit_card', label_ru: 'Edit card', permission: 'EDIT_CARD', trigger: null }],
  });
}

function stubBackgroundReads(): void {
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 })));
}

describe('CardForm — I7 E55 card-instruction fields', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('offers the six caller statuses of the instruction, in its order', () => {
    seedEditable();
    stubBackgroundReads();
    renderCardForm();
    const select = screen.getByLabelText(E55_LABELS.callerStatus);
    const labels = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent)
      .filter((text) => text !== '');
    expect(labels).toEqual(E55_LABELS.callerStatuses);
  });

  it('commits the picked channel code as one setCardField command', async () => {
    const user = userEvent.setup();
    seedEditable();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (isBackgroundReadUrl(String(input))) {
        return jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 });
      }
      const body = JSON.parse(init?.body as string);
      expect(body.field_path).toBe('applicant.channel');
      expect(body.new_value).toBe('MTS');
      return jsonResponse({ card: makeE55Card({ values: { 'applicant.channel': 'MTS' } }) });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderCardForm();
    await user.selectOptions(screen.getByLabelText(E55_LABELS.channel), E55_LABELS.channelMts);

    await waitFor(() => expect(useCardStore.getState().card?.values['applicant.channel']).toBe('MTS'));
    const commandCalls = fetchMock.mock.calls.filter(([input]) => !isBackgroundReadUrl(String(input)));
    expect(commandCalls).toHaveLength(1);
  });

  it('shows the injured count only once the casualties toggle is on', () => {
    seedEditable();
    stubBackgroundReads();
    const first = renderCardForm();
    expect(screen.queryByLabelText(E55_LABELS.casualtiesCount)).not.toBeInTheDocument();
    first.unmount();

    seedEditable({ values: { 'flags.casualties': true } });
    renderCardForm();
    const count = screen.getByLabelText(E55_LABELS.casualtiesCount);
    expect(count).toHaveAttribute('type', 'number');
  });

  it('shows the 103 block with its refusal toggle only for a 103 card, and commits true on a click', async () => {
    const user = userEvent.setup();
    seedEditable({ values: { 'incident.types': ['1'] } });
    stubBackgroundReads();
    const first = renderCardForm();
    expect(screen.queryByRole('button', { name: E55_LABELS.responseRefusedButton })).not.toBeInTheDocument();
    first.unmount();

    seedEditable({ values: { 'incident.types': ['22'] } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (isBackgroundReadUrl(String(input))) {
        return jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 });
      }
      const body = JSON.parse(init?.body as string);
      expect(body.field_path).toBe('flags.response_refused');
      expect(body.new_value).toBe(true);
      return jsonResponse({ card: makeE55Card({ values: { 'incident.types': ['22'], 'flags.response_refused': true } }) });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderCardForm();

    const block = container.querySelector<HTMLElement>('[data-slot="card-group-q_ambulance"]');
    expect(block).not.toBeNull();
    expect(within(block!).getByText(ru.operatorGroupQAmbulance)).toBeInTheDocument();
    expect(ru.operatorGroupQAmbulance).toBe(E55_LABELS.ambulanceBlock);
    const toggle = within(block!).getByRole('button', { name: E55_LABELS.responseRefusedButton });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);

    await waitFor(() => expect(useCardStore.getState().card?.values['flags.response_refused']).toBe(true));
    const commandCalls = fetchMock.mock.calls.filter(([input]) => !isBackgroundReadUrl(String(input)));
    expect(commandCalls).toHaveLength(1);
  });

  it('caps the description at 1999 characters and shows the reference counter', async () => {
    const user = userEvent.setup();
    seedEditable();
    stubBackgroundReads();
    const { container } = renderCardForm();
    const description = screen.getByLabelText(E55_LABELS.description);
    expect(description).toHaveAttribute('maxLength', '1999');
    const counter = container.querySelector('[data-slot="card-field-counter"]');
    expect(counter).toHaveTextContent('0 / 1999');
    await user.type(description, 'abc');
    expect(counter).toHaveTextContent('3 / 1999');
  });
});
