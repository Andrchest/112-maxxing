import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HandoffSection } from './handoff-section';
import { ru } from '@/shared/i18n/ru';
import { BUILDING_FIELD_SPEC_HIDDEN, DESCRIPTION_FIELD_SPEC, HOUSE_FIELD_SPEC, makeHandoffSnapshot } from './test-fixtures';

describe('HandoffSection — empty state for a DDS-only session (10.14 reading #9), verbatim otherwise', () => {
  it('renders the empty state when handoff is null', () => {
    render(<HandoffSection handoff={null} fieldSpecs={[]} />);
    expect(screen.getByText(ru.reportHandoffEmpty)).toBeInTheDocument();
  });

  it('renders recipient services and the frozen card_values, by the schema passed in fieldSpecs', () => {
    render(
      <HandoffSection
        handoff={makeHandoffSnapshot({ recipient_services: ['FIRE_RESCUE', 'POLICE'], card_values: { 'address.house': '72' } })}
        fieldSpecs={[HOUSE_FIELD_SPEC]}
      />,
    );
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText(ru.serviceTypePolice)).toBeInTheDocument();
    expect(screen.getByText(HOUSE_FIELD_SPEC.label_ru)).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
  });

  it('omits a field_specs entry that is not in this handoff snapshot card_values', () => {
    render(
      <HandoffSection
        handoff={makeHandoffSnapshot({ card_values: { 'address.house': '72' } })}
        fieldSpecs={[HOUSE_FIELD_SPEC, DESCRIPTION_FIELD_SPEC]}
      />,
    );
    expect(screen.getByText(HOUSE_FIELD_SPEC.label_ru)).toBeInTheDocument();
    expect(screen.queryByText(DESCRIPTION_FIELD_SPEC.label_ru)).not.toBeInTheDocument();
  });

  it('omits a field visible_when hides for this snapshot even when it has a value', () => {
    render(
      <HandoffSection
        handoff={makeHandoffSnapshot({ card_values: { 'address.house': '72', 'address.building': '3' } })}
        fieldSpecs={[HOUSE_FIELD_SPEC, BUILDING_FIELD_SPEC_HIDDEN]}
      />,
    );
    expect(screen.getByText(HOUSE_FIELD_SPEC.label_ru)).toBeInTheDocument();
    expect(screen.queryByText(BUILDING_FIELD_SPEC_HIDDEN.label_ru)).not.toBeInTheDocument();
  });
});
