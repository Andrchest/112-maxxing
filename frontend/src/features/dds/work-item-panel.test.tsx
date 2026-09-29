import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { WorkItemPanel } from './work-item-panel';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import {
  AMBULANCE_INCIDENT_TYPES_FIELD_SPEC,
  CLASSIFIER_CODE_FIELD_SPEC,
  RESPONSE_REFUSED_FIELD_SPEC,
  INCIDENT_TYPES_CHIP_FIELD_SPEC,
  Q_FIRE_WHERE_FIELD_SPEC,
  THREAT_TO_LIFE_HIDDEN_FIELD_SPEC,
  makeWorkItem,
  workItemFieldSpec,
} from './test-fixtures';

describe('WorkItemPanel — frozen card values, never a guessed value', () => {
  afterEach(() => {
    useWorkItemStore.getState().reset();
  });

  it('renders nothing when there is no work item yet', () => {
    const { container } = render(<WorkItemPanel />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the frozen card_values verbatim, including the operator-entered wrong house number', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem() });
    render(<WorkItemPanel />);
    expect(screen.getByText('72')).toBeInTheDocument();
  });

  it('renders every missing_field_paths entry using ddsMissingFieldNotice, never a guessed value', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem({ missing_field_paths: ['caller.phone'] }) });
    render(<WorkItemPanel />);
    expect(screen.getByText(ru.ddsMissingFieldNotice)).toBeInTheDocument();
  });

  // I4 E21 (owner decision 2026-09-25): the memo card has no «Получатели» badge row — the services
  // tab bar shows the recipients (`console-page.test.tsx`). Only the picker console, which has no
  // tab bar, asks for the row.
  // (The fixture's v1 card also carries a `recipients.services` card field, rendered as a card
  // group like any other schema field — that is the frozen card, not the badge row.)
  it('renders no recipients badge row by default', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem({ recipient_services: ['FIRE_RESCUE', 'AMBULANCE'] }) });
    const { container } = render(<WorkItemPanel />);
    expect(container.querySelector('[data-slot="dds-recipients-row"]')).toBeNull();
  });

  it('renders the recipient services as badges when the picker console asks for them', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem({ recipient_services: ['FIRE_RESCUE', 'AMBULANCE'] }) });
    const { container } = render(<WorkItemPanel showRecipients />);
    const row = container.querySelector<HTMLElement>('[data-slot="dds-recipients-row"]');
    expect(row).not.toBeNull();
    expect(within(row!).getByText(ru.ddsWorkItemRecipientsLabel)).toBeInTheDocument();
    expect(within(row!).getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(within(row!).getByText(ru.serviceTypeAmbulance)).toBeInTheDocument();
  });

  it('renders every field label from field_specs, not a hard-coded catalog (ui-check D-9)', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem() });
    render(<WorkItemPanel />);
    expect(screen.getByText(`${workItemFieldSpec('address.street').label_ru}:`)).toBeInTheDocument();
    expect(screen.getByText(`${workItemFieldSpec('address.house').label_ru}:`)).toBeInTheDocument();
  });

  it('omits a field that is neither filled nor listed missing (empty fields are omitted)', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_values: { 'address.house': '72' },
        missing_field_paths: [],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.queryByText(`${workItemFieldSpec('description.text').label_ru}:`)).not.toBeInTheDocument();
  });

  it('omits a field visible_when hides for this card (hidden fields are omitted)', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_values: { 'address.house': '72', 'flags.threat_to_life': false },
        missing_field_paths: [],
        field_specs: [workItemFieldSpec('address.house'), THREAT_TO_LIFE_HIDDEN_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.getByText(`${workItemFieldSpec('address.house').label_ru}:`)).toBeInTheDocument();
    expect(screen.queryByText(`${THREAT_TO_LIFE_HIDDEN_FIELD_SPEC.label_ru}:`)).not.toBeInTheDocument();
  });

  it('I3 E7a carry-over fix (b): renders incident.types with the reference wording, not the schema’s raw option label ("101")', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.getByText(ru.operatorGroupQFire)).toBeInTheDocument();
    expect(screen.queryByText(INCIDENT_TYPES_CHIP_FIELD_SPEC.options![0]!.label_ru)).not.toBeInTheDocument();
    expect(screen.queryByText('1')).not.toBeInTheDocument();
  });

  it('I3 E7a carry-over fix (b): shows the incident.classifier_code line from the card’s classifier value when present', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'], 'incident.classifier_code': 'fire: apartment' },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, CLASSIFIER_CODE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    // I7 E55 (owner decision Q9): the row is the reference's [VIS] classifier row — the 112 card's code.
    expect(screen.getByText(`${ru.ddsVisClassifierLabel}:`)).toBeInTheDocument();
    expect(screen.getByText('fire: apartment')).toBeInTheDocument();
    expect(screen.queryByText(`${CLASSIFIER_CODE_FIELD_SPEC.label_ru}:`)).not.toBeInTheDocument();
  });

  it('I7 E55: keeps the read-only [VIS] classifier row, empty, when the classifier has no value', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, CLASSIFIER_CODE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    const row = document.querySelector('[data-field-path="incident.classifier_code"]');
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent(`${ru.ddsVisClassifierLabel}:`);
    expect(row?.textContent?.trim()).toBe(`${ru.ddsVisClassifierLabel}:`);
    // Read-only: nothing on the row can change it.
    expect(row?.querySelector('input, select, textarea, button')).toBeNull();
  });

  it('I7 E55: a schema without incident.classifier_code (v1) shows no [VIS] classifier row', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem() });
    render(<WorkItemPanel />);
    expect(screen.queryByText(`${ru.ddsVisClassifierLabel}:`)).not.toBeInTheDocument();
  });

  it('I7 E55: the 103 refusal renders under the 103 dark bar as the reference button text', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['22'], 'flags.response_refused': true },
        missing_field_paths: [],
        field_specs: [AMBULANCE_INCIDENT_TYPES_FIELD_SPEC, RESPONSE_REFUSED_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    const bar = document.querySelector('[data-slot="dds-questionnaire-bar"]');
    expect(bar).not.toBeNull();
    expect(bar).toHaveTextContent(ru.operatorGroupQAmbulance);
    expect(bar).toHaveTextContent(RESPONSE_REFUSED_FIELD_SPEC.options![0]!.label_ru);
    expect(bar).not.toHaveTextContent(ru.factBooleanYes);
  });

  it('I7 E55: the DDS sentence shows the description the server sent, verbatim (the 03 cut is server-side)', () => {
    const cut = 'x'.repeat(100);
    useWorkItemStore.setState({
      workItem: makeWorkItem({ card_values: { 'description.text': cut }, missing_field_paths: [] }),
    });
    render(<WorkItemPanel />);
    expect(screen.getByText(cut)).toBeInTheDocument();
  });

  it('I3 E7a (manager review): the dark bar is titled by the selected incident type, not a static group heading', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'], 'q.fire.where': [Q_FIRE_WHERE_FIELD_SPEC.options![0]!.code] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, Q_FIRE_WHERE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    const bar = document.querySelector('[data-slot="dds-questionnaire-bar"]');
    expect(bar).not.toBeNull();
    expect(bar).toHaveTextContent(ru.operatorGroupQFire);
  });

  it('I3 E7a (manager review): the dark bar renders the field VALUE only, never its own label, and drops the separate incident.types line', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'], 'q.fire.where': [Q_FIRE_WHERE_FIELD_SPEC.options![0]!.code] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, Q_FIRE_WHERE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.getByText(Q_FIRE_WHERE_FIELD_SPEC.options![0]!.label_ru, { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(`${Q_FIRE_WHERE_FIELD_SPEC.label_ru}:`, { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByText(`${INCIDENT_TYPES_CHIP_FIELD_SPEC.label_ru}:`, { exact: false })).not.toBeInTheDocument();
  });

  it('I3 E7a (manager review): a classifier value still renders as its own separate row under the dark bar', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'], 'q.fire.where': [Q_FIRE_WHERE_FIELD_SPEC.options![0]!.code], 'incident.classifier_code': 'fire: apartment' },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, Q_FIRE_WHERE_FIELD_SPEC, CLASSIFIER_CODE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    const bar = document.querySelector('[data-slot="dds-questionnaire-bar"]');
    const classifierLine = document.querySelector('[data-slot="dds-incident-field-line"]');
    expect(classifierLine).not.toBeNull();
    expect(classifierLine).toHaveTextContent('fire: apartment');
    expect(bar).not.toHaveTextContent('fire: apartment');
  });
});

// I7 E55 (owner decision Q9): the DDS screen's two marks with the pencil — set by the DDS
// participant, default off, read-only until the pencil is pressed.
describe('WorkItemPanel — the DDS card marks (I7 E55)', () => {
  const MEMO_ACTIONS = [{ action_id: 'set_service_status', label_ru: 'status', permission: 'SET_SERVICE_STATUS' as const, trigger: null }];

  afterEach(() => {
    useWorkItemStore.getState().reset();
    vi.unstubAllGlobals();
  });

  it('shows both marks off by default, disabled, and no marks at all without a session (picker)', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem(), availableActions: [] });
    const { unmount } = render(<WorkItemPanel />);
    expect(document.querySelector('[data-slot="dds-card-marks"]')).toBeNull();
    unmount();

    render(<WorkItemPanel sessionId="sess-1" />);
    const chs = screen.getByRole('button', { name: ru.ddsMarkChs });
    const chp = screen.getByRole('button', { name: ru.ddsMarkChp });
    expect(chs).toHaveAttribute('aria-pressed', 'false');
    expect(chp).toHaveAttribute('aria-pressed', 'false');
    expect(chs).toBeDisabled();
    // No action offered (an instructor, or a closed stage): read-only, no pencil.
    expect(screen.queryByRole('button', { name: ru.ddsMarksEditButton })).not.toBeInTheDocument();
  });

  it('renders the marks the server holds', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem({ dds_marks: { chs: false, chp: true } }), availableActions: [] });
    render(<WorkItemPanel sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.ddsMarkChp })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: ru.ddsMarkChs })).toHaveAttribute('aria-pressed', 'false');
  });

  it('the pencil unlocks the toggles; a toggle sends the whole pair once and shows the answer', async () => {
    const user = userEvent.setup();
    useWorkItemStore.setState({ workItem: makeWorkItem({ dds_marks: { chs: false, chp: false } }), availableActions: MEMO_ACTIONS });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/dds/card-marks');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(init?.body as string)).toEqual({ chs: true, chp: false });
      return new Response(JSON.stringify(makeWorkItem({ dds_marks: { chs: true, chp: false } })), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<WorkItemPanel sessionId="sess-1" />);
    const chs = screen.getByRole('button', { name: ru.ddsMarkChs });
    expect(chs).toBeDisabled();
    await user.click(screen.getByRole('button', { name: ru.ddsMarksEditButton }));
    expect(chs).toBeEnabled();
    await user.click(chs);

    await waitFor(() => expect(useWorkItemStore.getState().workItem?.dds_marks).toEqual({ chs: true, chp: false }));
    expect(screen.getByRole('button', { name: ru.ddsMarkChs })).toHaveAttribute('aria-pressed', 'true');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
