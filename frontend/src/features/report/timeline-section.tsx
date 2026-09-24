// §29 item 4: complete event timeline. Renders `timeline` verbatim (already role-filtered and
// redacted server-side, R3) with a client-side actor filter and an event-type filter (the closest
// reading of "filter by stage/actor" the schema supports — `TimelineEntryView` carries no
// `stage`/`role_stage_id` field to filter by directly; see the report's "HLD gaps"). No
// virtualisation (brief: not required for this data size).
//
// Calls (I3 E6c backend, rendered since E6d): an entry of a call carries `call_id` and the call's
// party label `call_party_ru` («Вызов 112: абонент», «Звонок ДДС: Оператор 112»). When the report
// has any, a third filter shows one call's entries at a time and each call entry carries its party
// label; a report without them renders exactly as before.
//
// `highlightedSeqNo` supports the rule-evidence section's "scroll to / highlight this event"
// (§29 item 14): when it changes, the matching row scrolls into view and gets a highlight ring.
import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '@/shared/ui/badge';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { formatCallDurationMs } from '@/entities/call';
import type { ActorType, EventType, TimelineEntryView } from '@/shared/api';
import { actorTypeLabelRu } from './timeline-labels';
import { eventTypeLabelRu } from './event-type-labels';
import { timelineEntryRowId } from './timeline-row-id';
import { timelineCalls } from './call-groups';

interface TimelineSectionProps {
  timeline: readonly TimelineEntryView[];
  highlightedSeqNo?: number | null;
}

const ALL = 'ALL' as const;

export function TimelineSection({ timeline, highlightedSeqNo = null }: TimelineSectionProps) {
  const [actorFilter, setActorFilter] = useState<ActorType | typeof ALL>(ALL);
  const [eventTypeFilter, setEventTypeFilter] = useState<EventType | typeof ALL>(ALL);
  const [callFilter, setCallFilter] = useState<string>(ALL);
  const rowRefs = useRef(new Map<number, HTMLLIElement>());

  const actorOptions = useMemo(
    () => Array.from(new Set(timeline.map((entry) => entry.actor_type))).sort(),
    [timeline],
  );
  const eventTypeOptions = useMemo(
    () => Array.from(new Set(timeline.map((entry) => entry.event_type))).sort(),
    [timeline],
  );

  const callOptions = useMemo(() => timelineCalls(timeline), [timeline]);

  const filtered = timeline.filter(
    (entry) =>
      (actorFilter === ALL || entry.actor_type === actorFilter) &&
      (eventTypeFilter === ALL || entry.event_type === eventTypeFilter) &&
      (callFilter === ALL || entry.call_id === callFilter),
  );

  useEffect(() => {
    if (highlightedSeqNo === null) return;
    // jsdom (the test environment) has no `scrollIntoView` implementation; the optional call
    // makes this a no-op there instead of throwing, while real browsers still scroll.
    rowRefs.current.get(highlightedSeqNo)?.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  }, [highlightedSeqNo]);

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('reportTimelineTitle')}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {t('reportTimelineActorFilterLabel')}
            <select
              className="h-7 rounded-lg border border-input bg-transparent px-2 text-xs outline-none dark:bg-input/30"
              value={actorFilter}
              onChange={(event) => setActorFilter(event.target.value as ActorType | typeof ALL)}
            >
              <option value={ALL}>{t('reportTimelineFilterAll')}</option>
              {actorOptions.map((actor) => (
                <option key={actor} value={actor}>
                  {actorTypeLabelRu(actor)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {t('reportTimelineEventTypeFilterLabel')}
            <select
              className="h-7 rounded-lg border border-input bg-transparent px-2 text-xs outline-none dark:bg-input/30"
              value={eventTypeFilter}
              onChange={(event) => setEventTypeFilter(event.target.value as EventType | typeof ALL)}
            >
              <option value={ALL}>{t('reportTimelineFilterAll')}</option>
              {eventTypeOptions.map((eventType) => (
                <option key={eventType} value={eventType}>
                  {eventTypeLabelRu(eventType)}
                </option>
              ))}
            </select>
          </label>
          {callOptions.length > 0 ? (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {t('reportTimelineCallFilterLabel')}
              <select
                className="h-7 rounded-lg border border-input bg-transparent px-2 text-xs outline-none dark:bg-input/30"
                value={callFilter}
                data-slot="timeline-call-filter"
                onChange={(event) => setCallFilter(event.target.value)}
              >
                <option value={ALL}>{t('reportTimelineCallFilterAll')}</option>
                {callOptions.map((option) => (
                  <option key={option.callId} value={option.callId}>
                    {option.partyRu}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('reportTimelineEmpty')}</p>
        ) : (
          <ul className="flex max-h-96 flex-col gap-1 overflow-auto">
            {filtered.map((entry) => (
              <li
                key={entry.seq_no}
                id={timelineEntryRowId(entry.seq_no)}
                ref={(el) => {
                  if (el) rowRefs.current.set(entry.seq_no, el);
                  else rowRefs.current.delete(entry.seq_no);
                }}
                className={`flex items-baseline gap-2 rounded-md px-1.5 py-1 text-sm ${
                  entry.seq_no === highlightedSeqNo ? 'bg-primary/10 ring-1 ring-primary' : ''
                }`}
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {formatCallDurationMs(entry.monotonic_offset_ms)}
                </span>
                <span className="text-xs text-muted-foreground">{actorTypeLabelRu(entry.actor_type)}</span>
                {entry.call_id ? (
                  <Badge variant="outline" data-slot="timeline-call-party">
                    {entry.call_party_ru ?? t('reportCallPartyUnknown')}
                  </Badge>
                ) : null}
                <span>{entry.summary_ru}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
