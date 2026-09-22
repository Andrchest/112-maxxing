import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LiveOperatorCardSection } from './live-operator-card-section';
import { ru } from '@/shared/i18n/ru';
import { makeOperatorCardView } from './test-fixtures';

// `field_specs[].label_ru` is server-generated free text, given a non-Cyrillic override here only
// so the literal never trips `no-cyrillic-guard.test.ts` (same treatment
// `features/report/final-card-section.test.tsx` uses) — the component renders whatever the API
// sends verbatim, in Russian in production.
describe('LiveOperatorCardSection — the live OperatorCardView', () => {
  it('renders the empty state when card is null (no Operator 112 stage / DDS-only session)', () => {
    render(<LiveOperatorCardSection card={null} />);
    expect(screen.getByText(ru.instructorOperatorCardEmpty)).toBeInTheDocument();
  });

  it('renders each field grouped, using field_specs.label_ru', () => {
    render(
      <LiveOperatorCardSection
        card={makeOperatorCardView({
          values: { 'address.house': '72' },
          field_specs: [{ field_path: 'address.house', value_type: 'STRING', enum_name: null, label_ru: 'House label', scoring_relevant: true, required_for_handoff: true }],
        })}
      />,
    );
    expect(screen.getByText('House label')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
  });
});
