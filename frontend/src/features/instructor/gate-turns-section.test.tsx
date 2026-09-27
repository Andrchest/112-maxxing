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

  // I6 UX fix: a raw `fact_id` like `address.locality` used to render verbatim even though the
  // scenario carries a Russian label for it (`WorldTruthView.label_ru`) — this join covers it.
  it('labels a decision and the allowed/spontaneous lists via labelRu, falling back to the raw fact_id', () => {
    render(
      <GateTurnsSection
        gateTurns={[
          makeGateTurn({
            turn_index: 0,
            decisions: [makeGateDecision({ fact_id: 'address.locality', outcome: 'ALLOWED', reason: 'OK' })],
            allowed_fact_ids: ['address.locality'],
            spontaneous_attached: ['flags.threat_to_life'],
          }),
        ]}
        labelRu={{ 'address.locality': 'Locality' }}
      />,
    );
    expect(screen.getAllByText('Locality').length).toBeGreaterThan(0);
    expect(screen.queryByText('address.locality')).not.toBeInTheDocument();
    // no label for `flags.threat_to_life` in the map — falls back to the raw id.
    expect(screen.getByText(new RegExp('flags.threat_to_life'))).toBeInTheDocument();
  });
});
