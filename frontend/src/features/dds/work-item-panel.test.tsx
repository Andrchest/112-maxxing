import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WorkItemPanel } from './work-item-panel';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { INCIDENT_TYPES_CHIP_FIELD_SPEC, THREAT_TO_LIFE_HIDDEN_FIELD_SPEC, makeWorkItem, workItemFieldSpec } from './test-fixtures';

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

  it('renders the recipient services', () => {
    useWorkItemStore.setState({ workItem: makeWorkItem({ recipient_services: ['FIRE_RESCUE', 'AMBULANCE'] }) });
    render(<WorkItemPanel />);
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText(ru.serviceTypeAmbulance)).toBeInTheDocument();
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

  it('renders a v2 STRING_LIST option code as its label_ru, not the raw classifier code', () => {
    useWorkItemStore.setState({
      workItem: makeWorkItem({
        card_schema: 'v2',
        card_values: { 'incident.types': ['1'] },
        missing_field_paths: [],
        field_specs: [INCIDENT_TYPES_CHIP_FIELD_SPEC],
      }),
    });
    render(<WorkItemPanel />);
    expect(screen.getByText(INCIDENT_TYPES_CHIP_FIELD_SPEC.options![0]!.label_ru)).toBeInTheDocument();
    expect(screen.queryByText('1')).not.toBeInTheDocument();
  });
});
