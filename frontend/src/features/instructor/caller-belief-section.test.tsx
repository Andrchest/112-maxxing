import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CallerBeliefSection } from './caller-belief-section';
import { ru } from '@/shared/i18n/ru';
import { makeCallerBeliefView } from './test-fixtures';

describe('CallerBeliefSection — instructor-only caller belief', () => {
  it('renders the emotion and stress level', () => {
    render(<CallerBeliefSection callerBelief={makeCallerBeliefView({ emotion: 'FRIGHTENED', stress_level: 0.9 })} />);
    expect(screen.getByText(new RegExp(ru.emotionLabelFrightened))).toBeInTheDocument();
  });

  it('renders the empty state when there are no facts', () => {
    render(<CallerBeliefSection callerBelief={makeCallerBeliefView({ facts: {}, knowledge: {}, certainty: {}, revealed_fact_ids: [] })} />);
    expect(screen.getByText(ru.instructorCallerBeliefEmpty)).toBeInTheDocument();
  });

  it('renders each fact with its knowledge state and marks revealed facts', () => {
    render(
      <CallerBeliefSection
        callerBelief={makeCallerBeliefView({
          facts: { 'address.house': '72' },
          knowledge: { 'address.house': 'INCORRECT_BELIEF' },
          certainty: { 'address.house': 0.7 },
          revealed_fact_ids: ['address.house'],
        })}
      />,
    );
    expect(screen.getByText('address.house')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ru.knowledgeStateIncorrectBelief))).toBeInTheDocument();
    expect(screen.getByText(ru.instructorCallerBeliefRevealedLabel)).toBeInTheDocument();
  });
});
