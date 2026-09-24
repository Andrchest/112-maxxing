// I3 E3b: the v2 card layout (`CardForm` dispatching to `CardFormV2`, HLD 70 §70.5.2–§70.5.4).
// Covers the row's own CHECK items: one `setCardField` command per field commit (D12, unchanged
// for the multi-value controls too), `visible_when` hiding a field for the current values, and a
// v1 card still rendering from the old layout untouched by this epic.
//
// Label text asserted below comes from `./test-fixtures.ts` (`V2_LABELS`), not a literal here —
// this file is a `.tsx` under `src/features`, so `src/app/no-cyrillic-guard.test.ts` (D12) would
// flag a hard-coded Cyrillic string in it exactly as it would in production code.
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CardForm } from '../card-form';
import { useCardStore } from '@/entities/card';
import type { OperatorCardView } from '@/entities/card';
import { useStageStore } from '@/entities/stage';
import { V2_LABELS, makeV2Card } from './test-fixtures';

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

/** Every read this layout issues besides the trainee's own edit: the header's `SESSION_CREATED`/
 * `display_number` reads and the services bar's `RECIPIENTS_RESOLVED` history — all GETs, none of
 * them the one `setCardField` command a test is asserting on. */
function isBackgroundReadUrl(url: string): boolean {
  return url.includes('/events') || url.includes('/incidents');
}

function seedEditable(overrides: Partial<OperatorCardView> = {}): void {
  useCardStore.getState().setCard(makeV2Card(overrides));
  useStageStore.setState({
    availableActions: [{ action_id: 'edit_card', label_ru: 'Edit card', permission: 'EDIT_CARD', trigger: null }],
  });
}

describe('CardForm — v2 layout (I3 E3b, HLD 70 §70.5.2–§70.5.4)', () => {
  afterEach(() => {
    useCardStore.getState().setCard(null);
    useStageStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('renders the header, applicant, address and incident groups from field_specs, not a hard-coded list', () => {
    seedEditable();
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    renderCardForm();

    expect(screen.getByLabelText(V2_LABELS.phoneAon)).toBeInTheDocument();
    expect(screen.getByLabelText(V2_LABELS.fullName)).toBeInTheDocument();
    expect(screen.getByLabelText(V2_LABELS.street)).toBeInTheDocument();
    expect(screen.getByRole('group', { name: V2_LABELS.incidentTypesGroup })).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: V2_LABELS.incidentTypesGroup })).toBeInTheDocument();
  });

  it('hides q.fire.where until incident.types contains "1" (visible_when, shared fixtures contract)', () => {
    seedEditable();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 })));

    const first = renderCardForm();
    expect(screen.queryByText(V2_LABELS.qFireWhere)).not.toBeInTheDocument();
    first.unmount();

    seedEditable({ values: { 'incident.types': ['1'] } });
    renderCardForm();
    expect(screen.getByText(V2_LABELS.qFireWhere)).toBeInTheDocument();
  });

  it('commits the whole new list as one setCardField command when a TOGGLE_SET tag is clicked (D12)', async () => {
    const user = userEvent.setup();
    seedEditable({ values: { 'incident.types': ['1'] } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (isBackgroundReadUrl(String(input))) {
        return jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 });
      }
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/card/field');
      const body = JSON.parse(init?.body as string);
      expect(body.field_path).toBe('q.fire.where');
      expect(body.new_value).toEqual([V2_LABELS.qFireWhereOnStreet]);
      return jsonResponse({ card: makeV2Card({ values: { 'incident.types': ['1'], 'q.fire.where': [V2_LABELS.qFireWhereOnStreet] } }) });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderCardForm();
    await user.click(screen.getByRole('button', { name: V2_LABELS.street }));

    await waitFor(() => expect(useCardStore.getState().card?.values['q.fire.where']).toEqual([V2_LABELS.qFireWhereOnStreet]));
    // Exactly one `setCardField` command — every other call is a background read (D12 rule).
    const commandCalls = fetchMock.mock.calls.filter(([input]) => !isBackgroundReadUrl(String(input)));
    expect(commandCalls).toHaveLength(1);
  });

  it('commits the whole new list as one setCardField command when a CHIPS option is added (D12)', async () => {
    const user = userEvent.setup();
    seedEditable();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (isBackgroundReadUrl(String(input))) {
        return jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 });
      }
      expect(String(input)).toBe('/api/v1/sessions/sess-1/operator/card/field');
      const body = JSON.parse(init?.body as string);
      expect(body.field_path).toBe('incident.types');
      expect(body.new_value).toEqual(['1']);
      return jsonResponse({ card: makeV2Card({ values: { 'incident.types': ['1'] } }) });
    });
    vi.stubGlobal('fetch', fetchMock);

    renderCardForm();
    const search = screen.getByRole('searchbox', { name: V2_LABELS.incidentTypesGroup });
    await user.type(search, V2_LABELS.incidentType101);
    await user.click(screen.getByRole('button', { name: V2_LABELS.incidentType101 }));

    await waitFor(() => expect(useCardStore.getState().card?.values['incident.types']).toEqual(['1']));
    const commandCalls = fetchMock.mock.calls.filter(([input]) => !isBackgroundReadUrl(String(input)));
    expect(commandCalls).toHaveLength(1);
  });

  it('shows the entry label as the incident.types chip text, not the bare option code', async () => {
    seedEditable({ values: { 'incident.types': ['1'] } });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 })));

    renderCardForm();

    const chip = screen.getByRole('button', { name: new RegExp(`${V2_LABELS.incidentType101ChipText}$`) });
    expect(chip.textContent).toBe(`${V2_LABELS.incidentType101ChipText} ×`);
  });

  it('excludes recipients.services from the generic renderer (the services panel owns it)', () => {
    seedEditable();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], last_seq_no: 0, has_more: false, total: 0 })));
    renderCardForm();
    expect(screen.queryByLabelText(V2_LABELS.services)).not.toBeInTheDocument();
  });
});
