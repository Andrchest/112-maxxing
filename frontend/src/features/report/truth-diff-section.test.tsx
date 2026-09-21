import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TruthDiffSection } from './truth-diff-section';
import { ru } from '@/shared/i18n/ru';
import { makeTruthDiffEntry } from './test-fixtures';

describe('TruthDiffSection — rendered only when the API returned entries', () => {
  it('renders nothing for an empty array (viewer may not see it, or nothing to compare)', () => {
    const { container } = render(<TruthDiffSection entries={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the label, verdict badge and both values for each entry', () => {
    // `label_ru` is server-generated free text; a non-Cyrillic override here only avoids tripping
    // `no-cyrillic-guard.test.ts`, which scans every .tsx source file.
    render(<TruthDiffSection entries={[makeTruthDiffEntry({ label_ru: 'House label', world_value: '27', card_value: '72', verdict: 'MISMATCH' })]} />);
    expect(screen.getByText('House label')).toBeInTheDocument();
    expect(screen.getByText(ru.truthDiffVerdictMismatch)).toBeInTheDocument();
    expect(screen.getByText(/27/)).toBeInTheDocument();
    expect(screen.getByText(/72/)).toBeInTheDocument();
  });

  it.each(['MATCH', 'MISMATCH', 'MISSING', 'NOT_COMPARABLE'] as const)('renders the Russian verdict badge for %s', (verdict) => {
    render(<TruthDiffSection entries={[makeTruthDiffEntry({ verdict })]} />);
    const labelKey = {
      MATCH: ru.truthDiffVerdictMatch,
      MISMATCH: ru.truthDiffVerdictMismatch,
      MISSING: ru.truthDiffVerdictMissing,
      NOT_COMPARABLE: ru.truthDiffVerdictNotComparable,
    }[verdict];
    expect(screen.getByText(labelKey)).toBeInTheDocument();
  });
});
