// `BarChart` (I7 E46a, owner item 6) — a small accessible SVG bar chart, no charting dependency
// (manager decision): one `<rect>` per datum, a `<title>` tooltip on each bar, and a «Показать
// таблицей» toggle rendering the same numbers as a `<table>`. Themed entirely from CSS custom
// properties (`chart-tokens.ts`), so it repaints for free on a light/dark switch.
import { useState } from 'react';
import { t } from '@/shared/i18n';
import { ChartTableToggle } from './chart-table-toggle';
import { CHART_AXIS_STROKE, CHART_AXIS_TEXT, CHART_BAR_FILL } from './chart-tokens';

export interface BarChartDatum {
  key: string;
  label: string;
  value: number;
}

export interface BarChartProps {
  title: string;
  data: readonly BarChartDatum[];
  emptyMessage: string;
  /** The table view's value column header. */
  valueColumnLabel: string;
  formatValue?: (value: number) => string;
}

const VIEW_WIDTH = 480;
const VIEW_HEIGHT = 220;
const MARGIN = { top: 12, right: 8, bottom: 28, left: 28 };

function defaultFormat(value: number): string {
  return String(Math.round(value));
}

export function BarChart({ title, data, emptyMessage, valueColumnLabel, formatValue = defaultFormat }: BarChartProps) {
  const [showTable, setShowTable] = useState(false);

  const plotWidth = VIEW_WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = VIEW_HEIGHT - MARGIN.top - MARGIN.bottom;
  const maxValue = Math.max(1, ...data.map((datum) => datum.value));
  const slotWidth = data.length > 0 ? plotWidth / data.length : plotWidth;
  const barWidth = Math.max(4, slotWidth * 0.6);

  return (
    <div data-slot="bar-chart" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        {data.length > 0 ? <ChartTableToggle showTable={showTable} onToggle={() => setShowTable((value) => !value)} /> : null}
      </div>
      {data.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-slot="bar-chart-empty">
          {emptyMessage}
        </p>
      ) : showTable ? (
        <table className="w-full border-collapse text-sm" data-slot="bar-chart-table">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="p-2 font-medium">{t('chartColumnLabel')}</th>
              <th className="p-2 font-medium">{valueColumnLabel}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((datum) => (
              <tr key={datum.key} className="border-b border-border/60" data-slot="bar-chart-table-row">
                <td className="p-2">{datum.label}</td>
                <td className="p-2 tabular-nums">{formatValue(datum.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <svg
          role="img"
          aria-label={title}
          viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
          className="h-auto w-full"
          data-slot="bar-chart-svg"
        >
          <title>{title}</title>
          <line
            x1={MARGIN.left}
            y1={MARGIN.top}
            x2={MARGIN.left}
            y2={MARGIN.top + plotHeight}
            stroke={CHART_AXIS_STROKE}
          />
          <line
            x1={MARGIN.left}
            y1={MARGIN.top + plotHeight}
            x2={VIEW_WIDTH - MARGIN.right}
            y2={MARGIN.top + plotHeight}
            stroke={CHART_AXIS_STROKE}
          />
          {data.map((datum, index) => {
            const barHeight = (datum.value / maxValue) * plotHeight;
            const x = MARGIN.left + index * slotWidth + (slotWidth - barWidth) / 2;
            const y = MARGIN.top + plotHeight - barHeight;
            return (
              <g key={datum.key}>
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={Math.max(0, barHeight)}
                  style={{ fill: CHART_BAR_FILL }}
                  data-slot="bar-chart-bar"
                >
                  <title>{`${datum.label}: ${formatValue(datum.value)}`}</title>
                </rect>
                <text
                  x={x + barWidth / 2}
                  y={MARGIN.top + plotHeight + 14}
                  textAnchor="middle"
                  fontSize="9"
                  style={{ fill: CHART_AXIS_TEXT }}
                >
                  {datum.label}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
