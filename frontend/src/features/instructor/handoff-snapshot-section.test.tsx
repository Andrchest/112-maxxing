import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HandoffSnapshotSection } from './handoff-snapshot-section';
import { ru } from '@/shared/i18n/ru';
import { makeHandoffSnapshot, makeOperatorCardView } from './test-fixtures';

// See `live-operator-card-section.test.tsx`: `label_ru` overridden to non-Cyrillic text only to
// keep the literal out of `no-cyrillic-guard.test.ts`'s scan.
describe('HandoffSnapshotSection — the immutable HandoffSnapshot', () => {
  it('renders the empty state when there is no handoff yet', () => {
    render(<HandoffSnapshotSection handoff={null} card={null} />);
    expect(screen.getByText(ru.reportHandoffEmpty)).toBeInTheDocument();
  });

  it('renders recipient services and each field, labelled from the live card field_specs', () => {
    render(
      <HandoffSnapshotSection
        handoff={makeHandoffSnapshot({ card_values: { 'address.house': '72' }, recipient_services: ['FIRE_RESCUE'] })}
        card={makeOperatorCardView({
          field_specs: [{ field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'House label', scoring_relevant: true, required_for_handoff: true }],
        })}
      />,
    );
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText('House label')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
  });

  it('falls back to the raw field_path when card is null', () => {
    render(<HandoffSnapshotSection handoff={makeHandoffSnapshot({ card_values: { 'address.house': '72' } })} card={null} />);
    expect(screen.getByText('address.house')).toBeInTheDocument();
  });
});
