import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { FinalCardSection } from './final-card-section';
import { ru } from '@/shared/i18n/ru';
import { makeOperatorCardView } from './test-fixtures';

// `field_specs[].label_ru` is server-generated free text, given a non-Cyrillic override here only
// so the literal never trips `no-cyrillic-guard.test.ts` — the component renders whatever the API
// sends verbatim, in Russian in production.
describe('FinalCardSection — renders final_card verbatim, grouped by field-path prefix', () => {
  it('renders each field label and its formatted value', () => {
    render(
      <FinalCardSection
        card={makeOperatorCardView({
          field_specs: [
            { field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'House label', scoring_relevant: true, required_for_handoff: true },
            { field_path: 'flags.threat_to_life', value_type: 'BOOLEAN', enum_name: null, label_ru: 'Threat flag', scoring_relevant: true, required_for_handoff: true },
          ],
        })}
      />,
    );
    expect(screen.getByText('House label')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('Threat flag')).toBeInTheDocument();
    expect(screen.getByText(ru.factBooleanYes)).toBeInTheDocument();
  });

  it('renders factValueEmpty for a field the operator never set', () => {
    render(
      <FinalCardSection
        card={makeOperatorCardView({
          values: {},
          field_specs: [{ field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'House label', scoring_relevant: true, required_for_handoff: true }],
        })}
      />,
    );
    expect(screen.getByText(ru.factValueEmpty)).toBeInTheDocument();
  });
});
