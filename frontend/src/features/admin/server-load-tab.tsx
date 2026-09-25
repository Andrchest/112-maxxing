// «Нагрузка» tab (I4 E30, 71 §71.7 → E29, 71 §71.6): CPU/memory/disk/GPU (`getServerLoad`, ТЗ
// ¶208, ¶289). SPEC §27's rule is reused verbatim here: a metric the server could not read comes
// back `null`, and this tab renders «нет данных» for it — never a bare `0`, which would read as a
// real (and false) zero-load reading.
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { getServerLoad, problemMessageRu, queryKeys, type ProblemCode } from '@/shared/api';

const POLL_INTERVAL_MS = 5000;

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

/** `null` -> «нет данных» (SPEC §27); otherwise the rounded value with its unit — never `0` for an
 * unread metric, since `0` is indistinguishable from a real zero reading. */
function formatMetric(value: number | null, unit: string): string {
  if (value === null) return t('adminNoData');
  return `${Math.round(value * 10) / 10} ${unit}`;
}

function formatPair(used: number | null, total: number | null, unit: string): string {
  if (used === null || total === null) return t('adminNoData');
  return `${formatMetric(used, unit)} / ${formatMetric(total, unit)}`;
}

export function ServerLoadTab() {
  const loadQuery = useQuery({
    queryKey: queryKeys.admin.serverLoad(),
    queryFn: getServerLoad,
    refetchInterval: POLL_INTERVAL_MS,
  });

  const load = loadQuery.data;

  return (
    <Card data-slot="admin-server-load">
      <CardHeader>
        {load ? <p className="text-xs text-muted-foreground">{t('adminLoadSampledAtLabel')}: {formatTimestampRu(load.sampled_at)}</p> : null}
      </CardHeader>
      <CardContent>
        {loadQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('adminLoadLoading')}</p> : null}
        {loadQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(loadQuery.error)}
          </p>
        ) : null}
        {load ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm" data-slot="admin-server-load-metrics">
            <dt className="text-muted-foreground">{t('adminLoadCpuLabel')}</dt>
            <dd className="tabular-nums" data-slot="admin-load-cpu">
              {formatMetric(load.cpu_percent, '%')}
            </dd>
            <dt className="text-muted-foreground">{t('adminLoadMemoryLabel')}</dt>
            <dd className="tabular-nums" data-slot="admin-load-memory">
              {formatPair(load.memory_used_mb, load.memory_total_mb, t('adminUnitMb'))}
            </dd>
            <dt className="text-muted-foreground">{t('adminLoadDiskLabel')}</dt>
            <dd className="tabular-nums" data-slot="admin-load-disk">
              {formatPair(load.disk_used_gb, load.disk_total_gb, t('adminUnitGb'))}
            </dd>
            <dt className="text-muted-foreground">{t('adminLoadGpuLabel')}</dt>
            <dd className="tabular-nums" data-slot="admin-load-gpu">
              {formatPair(load.gpu_memory_used_mb, load.gpu_memory_total_mb, t('adminUnitMb'))}
            </dd>
          </dl>
        ) : null}
      </CardContent>
    </Card>
  );
}
