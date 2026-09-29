// Shared colour tokens for the small SVG charts in this folder (I7 E46a, owner item 6). Every
// colour is a CSS custom property already defined in `index.css` for both themes
// (`--color-chart-1`..`--color-chart-5`, `--color-border`, `--color-muted`,
// `--color-muted-foreground`) — never a hard-coded hex, so a theme switch repaints every chart
// for free, the same way it already repaints every `bg-primary`/`text-muted-foreground` element.
export const CHART_BAR_FILL = 'var(--color-chart-2)';
export const CHART_LINE_STROKE = 'var(--color-chart-2)';
export const CHART_LINE_POINT_FILL = 'var(--color-chart-4)';
export const CHART_AXIS_STROKE = 'var(--color-border)';
export const CHART_AXIS_TEXT = 'var(--color-muted-foreground)';
export const CHART_NO_DATA_FILL = 'var(--color-muted)';

/** A sequential fill for a heatmap cell, `0…100` — `--color-muted` (0 %) to `--color-chart-5`
 * (100 %), mixed in `oklch` so it stays perceptually even in both themes. */
export function heatmapCellFill(percent: number): string {
  const clamped = Math.max(0, Math.min(100, percent));
  return `color-mix(in oklch, var(--color-chart-5) ${clamped}%, var(--color-muted))`;
}
