import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { WorkItemPanel } from './work-item-panel';
import { useWorkItemStore } from '@/entities/work-item';
import { ru } from '@/shared/i18n/ru';
import { makeWorkItem } from './test-fixtures';

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
});
