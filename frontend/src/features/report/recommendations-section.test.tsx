import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RecommendationsSection } from './recommendations-section';
import { ru } from '@/shared/i18n/ru';
import type { RecommendationView } from '@/shared/api';

// I7 E54 (G10): renders `SessionReport.recommendations` verbatim, in the server's own order.
describe('RecommendationsSection — renders SessionReport.recommendations verbatim', () => {
  it('renders the empty state when nothing failed', () => {
    render(<RecommendationsSection recommendations={[]} />);
    expect(screen.getByText(ru.reportRecommendationsEmpty)).toBeInTheDocument();
  });

  it('renders one line per recommendation, in the given order', () => {
    // Server-generated `text_ru`, given non-Cyrillic placeholders here only so this literal never
    // trips `no-cyrillic-guard.test.ts` — the component renders whatever the API returns.
    const recommendations: RecommendationView[] = [
      { category: 'CARD_QUALITY', text_ru: 'Card quality advice text' },
      { category: 'COMMUNICATION', text_ru: 'Communication advice text' },
    ];
    render(<RecommendationsSection recommendations={recommendations} />);
    const items = screen.getAllByText(/advice text/);
    expect(items).toHaveLength(2);
    expect(screen.getByText('Card quality advice text')).toBeInTheDocument();
    expect(screen.getByText('Communication advice text')).toBeInTheDocument();
    expect(screen.queryByText(ru.reportRecommendationsEmpty)).not.toBeInTheDocument();
  });
});
