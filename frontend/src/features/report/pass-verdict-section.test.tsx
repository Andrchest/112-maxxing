import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PassVerdictSection } from './pass-verdict-section';
import { makePassVerdict } from './test-fixtures';
import { ru } from '@/shared/i18n/ru';

// I5 E38 (Q-E9b-3): the report header shows the server's verdict and, when failed, which
// criteria did not hold — nothing is judged client-side.
describe('PassVerdictSection', () => {
  it('shows a passed verdict with the criteria it was judged by', () => {
    render(<PassVerdictSection verdict={makePassVerdict()} />);
    expect(screen.getByText(ru.passVerdictPassed)).toBeInTheDocument();
    expect(document.querySelector('[data-slot="pass-verdict"]')).toHaveAttribute('data-passed', 'true');
    expect(document.querySelector('[data-slot="pass-verdict-failed"]')).toBeNull();
    const criteria = document.querySelector('[data-slot="pass-verdict-criteria"]');
    expect(criteria).toHaveTextContent(`${ru.passVerdictCriteriaMinScore} 70%`);
    expect(criteria).toHaveTextContent(ru.passVerdictCriteriaNoCritical);
  });

  it('shows a failed verdict and names every failed criterion', () => {
    render(
      <PassVerdictSection
        verdict={makePassVerdict({
          passed: false,
          failed_criteria: ['MIN_SCORE_PERCENT', 'CRITICAL_ERRORS'],
          score_percent: 55,
          critical_error_count: 2,
        })}
      />,
    );
    expect(screen.getByText(ru.passVerdictFailed)).toBeInTheDocument();
    const failed = document.querySelector('[data-slot="pass-verdict-failed"]');
    expect(failed).toHaveTextContent(`${ru.passVerdictCriterionMinScore}: 55% (${ru.passVerdictThreshold} 70%)`);
    expect(failed).toHaveTextContent(`${ru.passVerdictCriterionCriticalErrors}: 2`);
    expect(failed).not.toHaveTextContent(ru.passVerdictCriterionMaxFailedRules);
  });

  it('renders nothing without a verdict', () => {
    const { container } = render(<PassVerdictSection verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
