import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CriticalErrorsSection } from './critical-errors-section';
import { ru } from '@/shared/i18n/ru';
import { makeScoreResult } from './test-fixtures';

describe('CriticalErrorsSection — renders score_report.critical_errors verbatim', () => {
  it('renders the empty state when there are no critical errors', () => {
    render(<CriticalErrorsSection criticalErrors={[]} />);
    expect(screen.getByText(ru.reportCriticalErrorsEmpty)).toBeInTheDocument();
  });

  it('renders one row per critical error with its name and description', () => {
    // Server-generated `name_ru`/`description_ru` text, given non-Cyrillic placeholders here only
    // so this literal never trips `no-cyrillic-guard.test.ts` (which scans every .tsx source
    // file, not just component code) — the component itself renders whatever the API returns.
    render(<CriticalErrorsSection criticalErrors={[makeScoreResult({ rule_id: 'rule-x', name_ru: 'Rule X name', description_ru: 'Rule X description' })]} />);
    expect(screen.getByText('Rule X name')).toBeInTheDocument();
    expect(screen.getByText('Rule X description')).toBeInTheDocument();
  });
});
