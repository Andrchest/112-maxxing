import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HandoffSection } from './handoff-section';
import { ru } from '@/shared/i18n/ru';
import { makeHandoffSnapshot } from './test-fixtures';

describe('HandoffSection — empty state for a DDS-only session (10.14 reading #9), verbatim otherwise', () => {
  it('renders the empty state when handoff is null', () => {
    render(<HandoffSection handoff={null} />);
    expect(screen.getByText(ru.reportHandoffEmpty)).toBeInTheDocument();
  });

  it('renders recipient services and the frozen card_values', () => {
    render(<HandoffSection handoff={makeHandoffSnapshot({ recipient_services: ['FIRE_RESCUE', 'POLICE'], card_values: { 'address.house': '72' } })} />);
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText(ru.serviceTypePolice)).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
  });
});
