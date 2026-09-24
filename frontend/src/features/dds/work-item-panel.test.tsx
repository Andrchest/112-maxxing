import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WorkItemPanel } from './work-item-panel';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import {
  CLASSIFIER_CODE_FIELD_SPEC,
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
    expect(screen.getByText(`${CLASSIFIER_CODE_FIELD_SPEC.label_ru}:`)).toBeInTheDocument();
    expect(screen.getByText('fire: apartment')).toBeInTheDocument();
  });

  it('I3 E7a carry-over fix (b): omits the incident.classifier_code line when the classifier has no value', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC, CLASSIFIER_CODE_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.queryByText(`${CLASSIFIER_CODE_FIELD_SPEC.label_ru}:`)).not.toBeInTheDocument();
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
