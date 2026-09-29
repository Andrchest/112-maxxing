// `LineChart` (I7 E46a, owner item 6) — a small accessible SVG line chart over a fixed `0…100`
// range (every caller today plots a percent), no charting dependency (manager decision). A
// `<circle>` per point with a `<title>` tooltip, a line joining them (skipped for a single point),
// and a «Показать таблицей» toggle rendering the same numbers as a `<table>`.
import { useState } from 'react';
import { t } from '@/shared/i18n';
import { ChartTableToggle } from './chart-table-toggle';
import { CHART_AXIS_STROKE, CHART_AXIS_TEXT, CHART_LINE_POINT_FILL, CHART_LINE_STROKE } from './chart-tokens';

export interface LineChartPoint {
  key: string;
  /** The x-axis / table row label (a formatted date, a session index, …). */
  label: string;
  value: number;
}

export interface LineChartProps {
  title: string;
  data: readonly LineChartPoint[];
  emptyMessage: string;
  /** The table view's value column header. */
  valueColumnLabel: string;
  formatValue?: (value: number) => string;
  yMin?: number;
  yMax?: number;
}

const VIEW_WIDTH = 480;
const VIEW_HEIGHT = 220;
const MARGIN = { top: 12, right: 12, bottom: 24, left: 28 };

function defaultFormat(value: number): string {
  return `${Math.round(value)}%`;
}

export function LineChart({
  title,
  data,
  emptyMessage,
  valueColumnLabel,
  formatValue = defaultFormat,
  yMin = 0,
  yMax = 100,
}: LineChartProps) {
  const [showTable, setShowTable] = useState(false);

  const plotWidth = VIEW_WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = VIEW_HEIGHT - MARGIN.top - MARGIN.bottom;
  const range = yMax - yMin || 1;

  function xOf(index: number): number {
    return data.length > 1 ? MARGIN.left + (index / (data.length - 1)) * plotWidth : MARGIN.left + plotWidth / 2;
  }

  function yOf(value: number): number {
    const clamped = Math.max(yMin, Math.min(yMax, value));
    return MARGIN.top + plotHeight - ((clamped - yMin) / range) * plotHeight;
  }

  const pathD = data.map((point, index) => `${index === 0 ? 'M' : 'L'}${xOf(index)},${yOf(point.value)}`).join(' ');

  return (
    <div data-slot="line-chart" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">{title}</h3>
        {data.length > 0 ? <ChartTableToggle showTable={showTable} onToggle={() => setShowTable((value) => !value)} /> : null}
      </div>
      {data.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-slot="line-chart-empty">
          {emptyMessage}
        </p>
      ) : showTable ? (
        <table className="w-full border-collapse text-sm" data-slot="line-chart-table">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="p-2 font-medium">{t('chartColumnDate')}</th>
              <th className="p-2 font-medium">{valueColumnLabel}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((point) => (
              <tr key={point.key} className="border-b border-border/60" data-slot="line-chart-table-row">
                <td className="p-2">{point.label}</td>
                <td className="p-2 tabular-nums">{formatValue(point.value)}</td>
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
          data-slot="line-chart-svg"
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
          {data.length > 1 ? <path d={pathD} fill="none" stroke={CHART_LINE_STROKE} strokeWidth={2} data-slot="line-chart-path" /> : null}
          {data.map((point, index) => (
            <circle key={point.key} cx={xOf(index)} cy={yOf(point.value)} r={3.5} style={{ fill: CHART_LINE_POINT_FILL }} data-slot="line-chart-point">
              <title>{`${point.label}: ${formatValue(point.value)}`}</title>
            </circle>
          ))}
          <text x={MARGIN.left} y={MARGIN.top + plotHeight + 16} fontSize="9" style={{ fill: CHART_AXIS_TEXT }}>
            {data[0]?.label ?? ''}
          </text>
          {data.length > 1 ? (
            <text x={VIEW_WIDTH - MARGIN.right} y={MARGIN.top + plotHeight + 16} textAnchor="end" fontSize="9" style={{ fill: CHART_AXIS_TEXT }}>
              {data[data.length - 1]?.label ?? ''}
            </text>
          ) : null}
        </svg>
      )}
    </div>
  );
}
