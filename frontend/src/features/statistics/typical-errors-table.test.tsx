import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TypicalErrorsTable } from './typical-errors-table';
import { ru } from '@/shared/i18n/ru';
import type { TypicalErrorRow } from '@/shared/api';

// I7 E54 (G11): renders `TypicalErrors.rows` verbatim, in the server's own order.
describe('TypicalErrorsTable — renders TypicalErrors.rows verbatim', () => {
  it('renders the empty state when there are no rows', () => {
    render(<TypicalErrorsTable rows={[]} />);
    expect(screen.getByText(ru.typicalErrorsEmpty)).toBeInTheDocument();
  });

  it('renders one row per rule, in the given order, with its category and share', () => {
    const rows: TypicalErrorRow[] = [
      { rule_id: 'r1', name_ru: 'Rule one', category: 'CARD_QUALITY', failed_session_count: 3, session_count: 4, share_percent: 75 },
      { rule_id: 'r2', name_ru: 'Rule two', category: 'COMMUNICATION', failed_session_count: 1, session_count: 4, share_percent: 25 },
    ];
    render(<TypicalErrorsTable rows={rows} />);
    const trs = screen.getAllByRole('row').filter((row) => row.getAttribute('data-slot') === 'typical-errors-row');
    expect(trs).toHaveLength(2);
    expect(trs[0]).toHaveTextContent('Rule one');
    expect(trs[0]).toHaveTextContent(ru.scoringCategoryCardQuality);
    expect(trs[0]).toHaveTextContent('3 / 4');
    expect(trs[0]).toHaveTextContent('75%');
    expect(trs[1]).toHaveTextContent('Rule two');
    expect(trs[1]).toHaveTextContent('25%');
    expect(screen.queryByText(ru.typicalErrorsEmpty)).not.toBeInTheDocument();
  });
});
