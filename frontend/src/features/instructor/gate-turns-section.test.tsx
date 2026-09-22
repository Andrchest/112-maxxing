import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GateTurnsSection } from './gate-turns-section';
import { ru } from '@/shared/i18n/ru';
import { makeGateDecision, makeGateTurn } from './test-fixtures';

describe('GateTurnsSection — what the caller was allowed to say per turn', () => {
  it('renders the empty state when no turn has happened yet', () => {
    render(<GateTurnsSection gateTurns={[]} />);
    expect(screen.getByText(ru.instructorGateTurnsEmpty)).toBeInTheDocument();
  });

  it('renders each decision with its outcome and reason', () => {
    render(
      <GateTurnsSection
        gateTurns={[
          makeGateTurn({
            turn_index: 0,
            decisions: [makeGateDecision({ fact_id: 'address.house', outcome: 'WITHHELD', reason: 'CALLER_DOES_NOT_KNOW' })],
            withheld_count: 1,
          }),
        ]}
      />,
    );
    expect(screen.getByText(`${ru.instructorGateTurnLabel} 1`)).toBeInTheDocument();
    expect(screen.getByText(ru.gateOutcomeWithheld)).toBeInTheDocument();
    expect(screen.getByText('address.house')).toBeInTheDocument();
    expect(screen.getByText(ru.gateReasonCallerDoesNotKnow)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`${ru.instructorGateTurnWithheldCountLabel}: 1`))).toBeInTheDocument();
  });

  it('renders spontaneous_attached only when non-empty', () => {
    render(<GateTurnsSection gateTurns={[makeGateTurn({ spontaneous_attached: ['flags.threat_to_life'] })]} />);
    expect(screen.getByText(new RegExp(ru.instructorGateTurnSpontaneousLabel))).toBeInTheDocument();
  });
});
