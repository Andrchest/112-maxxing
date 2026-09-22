import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WorldTruthSection } from './world-truth-section';
import { ru } from '@/shared/i18n/ru';
import { makeWorldTruthView } from './test-fixtures';

describe('WorldTruthSection — instructor-only ground truth', () => {
  it('is clearly titled as instructor-only', () => {
    render(<WorldTruthSection worldTruth={makeWorldTruthView()} />);
    expect(screen.getByText(ru.instructorWorldTruthTitle)).toBeInTheDocument();
  });

  it('renders the empty state when there are no facts', () => {
    render(<WorldTruthSection worldTruth={makeWorldTruthView({ facts: {}, value_types: {} })} />);
    expect(screen.getByText(ru.instructorWorldTruthEmpty)).toBeInTheDocument();
  });

  it('renders each fact by its label_ru and value', () => {
    const worldTruth = makeWorldTruthView({ facts: { 'address.house': '27' } });
    render(<WorldTruthSection worldTruth={worldTruth} />);
    expect(screen.getByText(worldTruth.label_ru!['address.house']!)).toBeInTheDocument();
    expect(screen.getByText('27')).toBeInTheDocument();
  });

  it('falls back to the raw fact id when label_ru has no entry for it (E20-E R11)', () => {
    render(<WorldTruthSection worldTruth={makeWorldTruthView({ facts: { 'address.house': '27' }, label_ru: {} })} />);
    expect(screen.getByText('address.house')).toBeInTheDocument();
    expect(screen.getByText('27')).toBeInTheDocument();
  });
});
