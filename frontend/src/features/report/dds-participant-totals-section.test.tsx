import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DdsParticipantTotalsSection } from './dds-participant-totals-section';
import { ru } from '@/shared/i18n/ru';
import { makeDdsParticipantTotals } from './test-fixtures';

describe('DdsParticipantTotalsSection — renders dds_participant_totals verbatim', () => {
  it('renders the empty state when there are no totals', () => {
    render(<DdsParticipantTotalsSection totals={[]} />);
    expect(screen.getByText(ru.reportDdsParticipantTotalsEmpty)).toBeInTheDocument();
  });

  it('renders one row per participant with their name, service and counts', () => {
    render(
      <DdsParticipantTotalsSection
        totals={[
          makeDdsParticipantTotals({ user_id: 'u1', display_name_ru: 'Trainee One', assigned_service_id: 'FIRE_RESCUE', legs: 2, accepted: 2, completed: 1 }),
          makeDdsParticipantTotals({ user_id: 'u2', display_name_ru: 'Trainee Two', assigned_service_id: null, legs: 0 }),
        ]}
      />,
    );
    expect(screen.getByText('Trainee One')).toBeInTheDocument();
    expect(screen.getByText('Trainee Two')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ru.serviceTypeFireRescue))).toBeInTheDocument();
  });
});
