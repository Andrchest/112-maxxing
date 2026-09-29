// «Показать таблицей» / «Показать графиком» (I7 E46a) — the one toggle every chart in this
// folder renders identically, so switching to the accessible table view (the same numbers, never
// a second source of truth) always looks and reads the same across the app.
import { t } from '@/shared/i18n';

export function ChartTableToggle({ showTable, onToggle }: { showTable: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="shrink-0 text-xs text-primary underline-offset-2 hover:underline"
      onClick={onToggle}
      aria-pressed={showTable}
      data-slot="chart-table-toggle"
    >
      {showTable ? t('chartsShowChart') : t('chartsShowTable')}
    </button>
  );
}
