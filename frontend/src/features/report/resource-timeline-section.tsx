// §29 item 12: resource timeline. Renders `resource_timeline` verbatim — one row per
// `RESOURCE_STATUS_CHANGED` step already projected by the backend.
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import type { ResourceTimelineEntryView } from '@/shared/api';
import { resourceStatusLabelRu } from './resource-labels';

interface ResourceTimelineSectionProps {
  entries: readonly ResourceTimelineEntryView[];
}

export function ResourceTimelineSection({ entries }: ResourceTimelineSectionProps) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportResourceTimelineTitle')}</h2>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportResourceTimelineEmpty')}</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {entries.map((entry, index) => (
              <li key={index} className="flex items-center gap-2 text-sm">
                <span className="font-mono text-xs text-muted-foreground">
                  {entry.at_offset_ms} {t('reportOffsetMsUnit')}
                </span>
                <span className="font-medium">{entry.callsign}</span>
                <Badge variant="outline">
                  {entry.previous_status === null ? t('factValueEmpty') : resourceStatusLabelRu(entry.previous_status)}
                </Badge>
                <span aria-hidden="true">→</span>
                <Badge variant="outline">{resourceStatusLabelRu(entry.new_status)}</Badge>
                <span className="text-xs text-muted-foreground">
                  ({t('reportResourceTimelineTriggerLabel')}: {entry.trigger})
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
