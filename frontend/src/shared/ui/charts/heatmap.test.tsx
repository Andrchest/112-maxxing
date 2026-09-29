import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Heatmap } from './heatmap';
import { ru } from '@/shared/i18n/ru';

describe('Heatmap (I7 E46a)', () => {
  it('renders the empty message and no toggle without rows or columns', () => {
    render(
      <Heatmap title="Errors by category" rowLabels={[]} columnLabels={[]} values={[]} emptyMessage="No data" legendLabel="Share, %" />,
    );
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a single cell, one row by one column', () => {
    render(
      <Heatmap
        title="Errors by category"
        rowLabels={['Ivanov']}
        columnLabels={['Workflow']}
        values={[[40]]}
        emptyMessage="No data"
        legendLabel="Share, %"
      />,
    );
    const cells = document.querySelectorAll('[data-slot="heatmap-cell"]');
    expect(cells).toHaveLength(1);
    expect(cells[0]?.querySelector('title')).toHaveTextContent('Ivanov, Workflow: 40%');
  });

  it('renders a grid of rows × columns and marks a null cell as «no data»', () => {
    render(
      <Heatmap
        title="Errors by category"
        rowLabels={['Ivanov', 'Petrov']}
        columnLabels={['Workflow', 'Timeliness']}
        values={[
          [40, null],
          [10, 90],
        ]}
        emptyMessage="No data"
        legendLabel="Share, %"
      />,
    );
    const cells = document.querySelectorAll('[data-slot="heatmap-cell"]');
    expect(cells).toHaveLength(4);
    expect(cells[1]?.querySelector('title')).toHaveTextContent(`Ivanov, Timeliness: ${ru.chartsNoData}`);
    expect(cells[3]?.querySelector('title')).toHaveTextContent('Petrov, Timeliness: 90%');
  });

  it('toggles to a table with the same numbers, «no data» for null, and back', async () => {
    const user = userEvent.setup();
    render(
      <Heatmap
        title="Errors by category"
        rowLabels={['Ivanov']}
        columnLabels={['Workflow', 'Timeliness']}
        values={[[40, null]]}
        emptyMessage="No data"
        legendLabel="Share, %"
      />,
    );
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: ru.chartsShowTable }));
    const row = document.querySelector('[data-slot="heatmap-table-row"]');
    expect(row).toHaveTextContent('Ivanov');
    expect(row).toHaveTextContent('40%');
    expect(row).toHaveTextContent(ru.chartsNoData);

    await user.click(screen.getByRole('button', { name: ru.chartsShowChart }));
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
