import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ServiceLegBlock } from './service-leg-block';
import { ru } from '@/shared/i18n/ru';
import { makeLeg, makeStatusEntry } from './test-fixtures';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

// `label_ru`/`service_name_ru`/`actor_display_ru` below are deliberately English placeholders,
// not real Russian — server-controlled wire data this component renders verbatim (same treatment
// `test-fixtures.ts`'s own `ACTIONS_BY_DDS_STAGE_STATE` comment documents), which also keeps this
// file importable without tripping `src/app/no-cyrillic-guard.test.ts` (Cyrillic UI strings must
// come from `ru.ts` through `t()`, never a literal in a `.tsx` source).
describe('ServiceLegBlock — the tab and its upward-growing popup (70 par.70.4.2/70.4.3, D16)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('collapsed: shows the service, its last status and time — no popup, no history, no pencil', () => {
    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({ is_mine: false, available_actions: [], service_name_ru: 'Service 101' })}
        expanded={false}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    expect(screen.getByText('Service 101')).toBeInTheDocument();
    expect(screen.getByText(ru.serviceResponseStatusReceived)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.ddsLegEditButton })).not.toBeInTheDocument();
    expect(screen.queryByText(ru.ddsLegHistoryEmpty)).not.toBeInTheDocument();
  });

  it('clicking the tab calls onToggle', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <ServiceLegBlock sessionId="sess-1" leg={makeLeg({ available_actions: [] })} expanded={false} onToggle={onToggle} onLegUpdated={() => {}} />,
    );
    await user.click(screen.getByRole('tab'));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('expanded: the popup shows the history entries with author, time and order number', () => {
    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({
          history: [
            makeStatusEntry({ event_id: 'e1', new_status: 'RECEIVED', actor_display_ru: 'System', at_offset_ms: 0 }),
            makeStatusEntry({ event_id: 'e2', new_status: 'ACCEPTED', actor_display_ru: 'Trainee One', at_offset_ms: 15000, order_number: '23' }),
          ],
        })}
        expanded={true}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    expect(screen.getByText('Trainee One')).toBeInTheDocument();
    expect(screen.getByText(/23/)).toBeInTheDocument();
    expect(screen.getByText(ru.serviceResponseStatusAccepted)).toBeInTheDocument();
  });

  // The E5c row's own vitest: "buttons only from available_actions" — the dropdown never invents a
  // status the server did not offer this caller on this leg.
  it("the pencil form dropdown offers exactly the leg's available_actions, nothing hard-coded", async () => {
    const user = userEvent.setup();
    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({
          available_actions: [
            { action_id: 'accept', label_ru: 'Accept', permission: 'SET_SERVICE_STATUS', trigger: 'accept' },
            { action_id: 'decline', label_ru: 'Decline', permission: 'SET_SERVICE_STATUS', trigger: 'decline' },
          ],
        })}
        expanded={true}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    await user.click(screen.getByRole('button', { name: ru.ddsLegEditButton }));
    const select = screen.getByLabelText(ru.ddsLegStatusLabel) as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((option) => option.textContent);
    expect(optionLabels).toEqual(['Accept', 'Decline']);
  });

  // The E5c row's own vitest: "comment field required client-side mirrors the 422" — «Не принята»
  // / «Отказ от выполнения работ» refuse the submit locally, before any request is sent.
  it('blocks submission of decline without a comment (client-side mirror of 422 COMMENT_REQUIRED)', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({
          available_actions: [{ action_id: 'decline', label_ru: 'Decline', permission: 'SET_SERVICE_STATUS', trigger: 'decline' }],
        })}
        expanded={true}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    await user.click(screen.getByRole('button', { name: ru.ddsLegEditButton }));
    await user.click(screen.getByRole('button', { name: ru.ddsLegFormConfirmButton }));

    expect(await screen.findByText(ru.ddsLegCommentRequiredNotice)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('submits the target status (not the trigger name) and calls onLegUpdated with the response', async () => {
    const user = userEvent.setup();
    const onLegUpdated = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/legs/assign-1/status');
      expect(JSON.parse(String(init?.body))).toEqual({ status: 'ACCEPTED', order_number: null, comment_ru: null });
      return jsonResponse(makeLeg({ response_status: 'ACCEPTED' }));
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({
          available_actions: [{ action_id: 'accept', label_ru: 'Accept', permission: 'SET_SERVICE_STATUS', trigger: 'accept' }],
        })}
        expanded={true}
        onToggle={() => {}}
        onLegUpdated={onLegUpdated}
      />,
    );
    await user.click(screen.getByRole('button', { name: ru.ddsLegEditButton }));
    await user.click(screen.getByRole('button', { name: ru.ddsLegFormConfirmButton }));

    await waitFor(() => expect(onLegUpdated).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onLegUpdated).toHaveBeenCalledWith(expect.objectContaining({ response_status: 'ACCEPTED' }));
  });

  it('103 (NO_REFUSAL) never offers refuse/decline — available_actions alone decides, this component asserts nothing itself', () => {
    render(
      <ServiceLegBlock
        sessionId="sess-1"
        leg={makeLeg({
          service_type: 'AMBULANCE',
          available_actions: [{ action_id: 'complete_without_brigade', label_ru: 'Completed without brigade', permission: 'SET_SERVICE_STATUS', trigger: 'complete_without_brigade' }],
        })}
        expanded={true}
        onToggle={() => {}}
        onLegUpdated={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: ru.ddsLegEditButton })).toBeInTheDocument();
  });
});
