import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { BarChart, type BarChartDatum } from './bar-chart';
import { ru } from '@/shared/i18n/ru';

const ONE: BarChartDatum[] = [{ key: 'a', label: '0-10%', value: 3 }];
const MANY: BarChartDatum[] = [
  { key: 'a', label: '0-10%', value: 3 },
  { key: 'b', label: '10-20%', value: 0 },
  { key: 'c', label: '20-30%', value: 7 },
];

describe('BarChart (I7 E46a)', () => {
  it('renders the empty message and no toggle when there is no data', () => {
    render(<BarChart title="Distribution" data={[]} emptyMessage="No data" valueColumnLabel="Count" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a single bar', () => {
    render(<BarChart title="Distribution" data={ONE} emptyMessage="No data" valueColumnLabel="Count" />);
    const bars = document.querySelectorAll('[data-slot="bar-chart-bar"]');
    expect(bars).toHaveLength(1);
    expect(bars[0]?.querySelector('title')).toHaveTextContent('0-10%: 3');
  });

  it('renders one bar per datum, in order', () => {
    render(<BarChart title="Distribution" data={MANY} emptyMessage="No data" valueColumnLabel="Count" />);
    const bars = document.querySelectorAll('[data-slot="bar-chart-bar"]');
    expect(bars).toHaveLength(3);
    expect(bars[2]?.querySelector('title')).toHaveTextContent('20-30%: 7');
  });

  it('toggles to a table with the same numbers and back', async () => {
    const user = userEvent.setup();
    render(<BarChart title="Distribution" data={MANY} emptyMessage="No data" valueColumnLabel="Count" />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.chartsShowTable }));
    const table = screen.getByRole('table');
    const rows = document.querySelectorAll('[data-slot="bar-chart-table-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent('20-30%');
    expect(rows[2]).toHaveTextContent('7');
    expect(table).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.chartsShowChart }));
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
