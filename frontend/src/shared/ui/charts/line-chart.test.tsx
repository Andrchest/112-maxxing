import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { LineChart, type LineChartPoint } from './line-chart';
import { ru } from '@/shared/i18n/ru';

const ONE: LineChartPoint[] = [{ key: 's1', label: '01.01', value: 42 }];
const MANY: LineChartPoint[] = [
  { key: 's1', label: '01.01', value: 42 },
  { key: 's2', label: '02.01', value: 58 },
  { key: 's3', label: '03.01', value: 71 },
];

describe('LineChart (I7 E46a)', () => {
  it('renders the empty message and no toggle when there is no data', () => {
    render(<LineChart title="Score over time" data={[]} emptyMessage="No data" valueColumnLabel="Score" />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a single point with no connecting line', () => {
    render(<LineChart title="Score over time" data={ONE} emptyMessage="No data" valueColumnLabel="Score" />);
    const points = document.querySelectorAll('[data-slot="line-chart-point"]');
    expect(points).toHaveLength(1);
    expect(points[0]?.querySelector('title')).toHaveTextContent('01.01: 42%');
    expect(document.querySelector('[data-slot="line-chart-path"]')).not.toBeInTheDocument();
  });

  it('renders one point per datum plus a connecting line, in order', () => {
    render(<LineChart title="Score over time" data={MANY} emptyMessage="No data" valueColumnLabel="Score" />);
    const points = document.querySelectorAll('[data-slot="line-chart-point"]');
    expect(points).toHaveLength(3);
    expect(points[2]?.querySelector('title')).toHaveTextContent('03.01: 71%');
    expect(document.querySelector('[data-slot="line-chart-path"]')).toBeInTheDocument();
  });

  it('toggles to a table with the same numbers and back', async () => {
    const user = userEvent.setup();
    render(<LineChart title="Score over time" data={MANY} emptyMessage="No data" valueColumnLabel="Score" />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.chartsShowTable }));
    const rows = document.querySelectorAll('[data-slot="line-chart-table-row"]');
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent('02.01');
    expect(rows[1]).toHaveTextContent('58%');

    await user.click(screen.getByRole('button', { name: ru.chartsShowChart }));
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
