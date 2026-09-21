import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CategoriesSection } from './categories-section';
import { ru } from '@/shared/i18n/ru';
import { makeScoreCategoryTotal } from './test-fixtures';

describe('CategoriesSection — one row per by_category entry, verbatim', () => {
  it('renders the Russian label and points for each category', () => {
    render(
      <CategoriesSection
        byCategory={[
          makeScoreCategoryTotal({ category: 'CARD_QUALITY', points_awarded: 5, max_points: 5 }),
          makeScoreCategoryTotal({ category: 'TIMELINESS', points_awarded: 2, max_points: 4 }),
        ]}
      />,
    );
    expect(screen.getByText(ru.scoringCategoryCardQuality)).toBeInTheDocument();
    expect(screen.getByText('5 / 5')).toBeInTheDocument();
    expect(screen.getByText(ru.scoringCategoryTimeliness)).toBeInTheDocument();
    expect(screen.getByText('2 / 4')).toBeInTheDocument();
  });

  it('renders no rows for an empty by_category', () => {
    render(<CategoriesSection byCategory={[]} />);
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });
});
