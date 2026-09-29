// `Heatmap` (I7 E46a, owner item 6) — a small accessible SVG heatmap grid, no charting dependency
// (manager decision). One `<rect>` per cell with a `<title>` tooltip, a sequential legend, and a
// «Показать таблицей» toggle rendering the same numbers as a `<table>`. `null` cells («Нет
// данных») render as a distinct muted swatch rather than `0 %`, so «no data» is never confused
// with «zero errors».
import { useState } from 'react';
import { t } from '@/shared/i18n';
import { ChartTableToggle } from './chart-table-toggle';
import { CHART_AXIS_TEXT, CHART_NO_DATA_FILL, heatmapCellFill } from './chart-tokens';

export interface HeatmapProps {
  title: string;
  rowLabels: readonly string[];
  columnLabels: readonly string[];
  /** `values[rowIndex][columnIndex]`; `null` = no data for that cell (0…`colorScaleMax` otherwise). */
  values: readonly (readonly (number | null)[])[];
  emptyMessage: string;
  legendLabel: string;
  formatValue?: (value: number) => string;
  /** The colour scale's own top (default `100`, a percent's own natural range) — a cell's fill
   * is `value / colorScaleMax`, so a raw count (e.g. sessions started) can supply its own max
   * without pretending to be a percent. `formatValue`/the table always show the raw `value`. */
  colorScaleMax?: number;
  /** Show every Nth column header (e.g. `3` for a 24-hour axis) — every one by default. */
  columnLabelStep?: number;
  rowLabelWidth?: number;
  /** A short caption for what the columns are (e.g. «Час (МСК)») — the corner cell in table
   * mode, a small label above the row gutter in the chart. Omitted by default. */
  columnAxisLabel?: string;
}

const CELL_HEIGHT = 22;
const COLUMN_HEADER_HEIGHT = 34;
const LEGEND_HEIGHT = 30;
const MARGIN = { top: 4, right: 8, bottom: 4 };

function defaultFormat(value: number): string {
  return `${Math.round(value)}%`;
}

export function Heatmap({
  title,
  rowLabels,
  columnLabels,
  values,
  emptyMessage,
  legendLabel,
  formatValue = defaultFormat,
  colorScaleMax = 100,
  columnLabelStep = 1,
  rowLabelWidth = 96,
  columnAxisLabel,
}: HeatmapProps) {
  const [showTable, setShowTable] = useState(false);
  const hasData = rowLabels.length > 0 && columnLabels.length > 0;
  const scaleMax = colorScaleMax > 0 ? colorScaleMax : 1;

  const viewWidth = 480;
  const plotWidth = viewWidth - rowLabelWidth - MARGIN.right;
  const cellWidth = columnLabels.length > 0 ? plotWidth / columnLabels.length : plotWidth;
  const plotTop = MARGIN.top + COLUMN_HEADER_HEIGHT;
  const plotHeight = rowLabels.length * CELL_HEIGHT;
  const viewHeight = plotTop + plotHeight + MARGIN.bottom + LEGEND_HEIGHT;

  return (
    <div data-slot="heatmap" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        {hasData ? <ChartTableToggle showTable={showTable} onToggle={() => setShowTable((value) => !value)} /> : null}
      </div>
      {!hasData ? (
        <p className="text-sm text-muted-foreground" data-slot="heatmap-empty">
          {emptyMessage}
        </p>
      ) : showTable ? (
        <table className="w-full border-collapse text-sm" data-slot="heatmap-table">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="p-2 font-medium">{columnAxisLabel}</th>
              {columnLabels.map((label) => (
                <th key={label} className="p-2 font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rowLabels.map((rowLabel, rowIndex) => (
              <tr key={rowLabel} className="border-b border-border/60" data-slot="heatmap-table-row">
                <td className="p-2">{rowLabel}</td>
                {columnLabels.map((columnLabel, columnIndex) => {
                  const value = values[rowIndex]?.[columnIndex] ?? null;
                  return (
                    <td key={columnLabel} className="p-2 tabular-nums">
                      {value === null ? t('chartsNoData') : formatValue(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <svg
          role="img"
          aria-label={title}
          viewBox={`0 0 ${viewWidth} ${viewHeight}`}
          className="h-auto w-full"
          data-slot="heatmap-svg"
        >
          <title>{title}</title>
          {columnAxisLabel ? (
            <text x={4} y={MARGIN.top + 8} fontSize="8" style={{ fill: CHART_AXIS_TEXT }} data-slot="heatmap-column-axis-label">
              {columnAxisLabel}
            </text>
          ) : null}
          {columnLabels.map((label, columnIndex) =>
            columnIndex % columnLabelStep === 0 ? (
              <text
                key={label}
                x={rowLabelWidth + columnIndex * cellWidth + cellWidth / 2}
                y={plotTop - 6}
                textAnchor="start"
                fontSize="8"
                transform={`rotate(-40 ${rowLabelWidth + columnIndex * cellWidth + cellWidth / 2} ${plotTop - 6})`}
                style={{ fill: CHART_AXIS_TEXT }}
              >
                {label}
              </text>
            ) : null,
          )}
          {rowLabels.map((rowLabel, rowIndex) => (
            <g key={rowLabel}>
              <text
                x={rowLabelWidth - 6}
                y={plotTop + rowIndex * CELL_HEIGHT + CELL_HEIGHT / 2 + 3}
                textAnchor="end"
                fontSize="9"
                style={{ fill: CHART_AXIS_TEXT }}
              >
                {rowLabel}
              </text>
              {columnLabels.map((columnLabel, columnIndex) => {
                const value = values[rowIndex]?.[columnIndex] ?? null;
                const x = rowLabelWidth + columnIndex * cellWidth;
                const y = plotTop + rowIndex * CELL_HEIGHT;
                return (
                  <rect
                    key={columnLabel}
                    x={x + 1}
                    y={y + 1}
                    width={Math.max(0, cellWidth - 2)}
                    height={CELL_HEIGHT - 2}
                    style={{ fill: value === null ? CHART_NO_DATA_FILL : heatmapCellFill((value / scaleMax) * 100) }}
                    data-slot="heatmap-cell"
                  >
                    <title>{`${rowLabel}, ${columnLabel}: ${value === null ? t('chartsNoData') : formatValue(value)}`}</title>
                  </rect>
                );
              })}
            </g>
          ))}
          {/* The legend: a 0…100 sequential strip, same scale `heatmapCellFill` uses. */}
          <g transform={`translate(${rowLabelWidth}, ${plotTop + plotHeight + 14})`}>
            <text x={0} y={-4} fontSize="9" style={{ fill: CHART_AXIS_TEXT }}>
              {legendLabel}
            </text>
            {Array.from({ length: 10 }, (_, step) => step * 10).map((percent) => (
              <rect
                key={percent}
                x={(percent / 10) * 12}
                y={2}
                width={12}
                height={10}
                style={{ fill: heatmapCellFill(percent) }}
              />
            ))}
            <text x={0} y={26} fontSize="8" style={{ fill: CHART_AXIS_TEXT }}>
              {formatValue(0)}
            </text>
            <text x={120} y={26} textAnchor="end" fontSize="8" style={{ fill: CHART_AXIS_TEXT }}>
              {formatValue(scaleMax)}
            </text>
          </g>
        </svg>
      )}
    </div>
  );
}
