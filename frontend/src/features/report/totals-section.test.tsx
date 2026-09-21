import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TotalsSection } from './totals-section';
import { ru } from '@/shared/i18n/ru';
import { makeScoreReport } from './test-fixtures';

describe('TotalsSection — displays the server totals verbatim, never a client-side sum', () => {
  it('renders total_points / total_max_points exactly as returned', () => {
    render(<TotalsSection scoreReport={makeScoreReport({ total_points: 42, total_max_points: 60 })} />);
    expect(screen.getByText('42 / 60')).toBeInTheDocument();
  });

  it('renders the title and computed_from_event_count', () => {
    render(<TotalsSection scoreReport={makeScoreReport({ computed_from_event_count: 17 })} />);
    expect(screen.getByText(ru.reportTotalsTitle)).toBeInTheDocument();
    expect(screen.getByText(/17/)).toBeInTheDocument();
  });
});
