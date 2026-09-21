// The transcript panel (SPEC §32: "a transcript may exist as a secondary panel"; D12 design
// decision #4: collapsed by default, read-only, never offers an action on its text). Fed by the
// two event types the OPERATOR_112 role actually receives dialogue text for
// (`docs/hld/40-realtime-protocol.md` §40.4): the trainee's own `ASR_FINAL` transcript and a
// caller utterance's `delivered_text` on `CALLER_UTTERANCE_INTERRUPTED` (barge-in). Everything
// else the caller says arrives only as audio (E11) — SPEC §32 deliberately keeps this a phone
// call, not a chat window.
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { ScrollArea } from '@/shared/ui/scroll-area';
import { t } from '@/shared/i18n';
import { useSessionEventsStore } from '@/entities/session';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

interface TranscriptLine {
  seqNo: number;
  speaker: 'operator' | 'caller';
  text: string;
}

function toLines(events: readonly SessionEventEnvelope[]): TranscriptLine[] {
  const lines: TranscriptLine[] = [];
  for (const event of events) {
    if (event.event_type === 'ASR_FINAL') {
      const text = (event.payload as { text?: string }).text;
      if (text) lines.push({ seqNo: event.seq_no, speaker: 'operator', text });
    } else if (event.event_type === 'CALLER_UTTERANCE_INTERRUPTED') {
      const text = (event.payload as { delivered_text?: string }).delivered_text;
      if (text) lines.push({ seqNo: event.seq_no, speaker: 'caller', text });
    }
  }
  return lines;
}

export function TranscriptPanel() {
  const events = useSessionEventsStore((state) => state.events);
  const [open, setOpen] = useState(false); // collapsed by default (D12 design decision #4)
  const lines = toLines(events);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('operatorTranscriptTitle')}</h2>
        <Button type="button" variant="ghost" size="sm" onClick={() => setOpen((value) => !value)}>
          {open ? t('operatorTranscriptHide') : t('operatorTranscriptShow')}
        </Button>
      </CardHeader>
      {open ? (
        <CardContent>
          <ScrollArea className="h-48">
            {lines.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('operatorTranscriptEmpty')}</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {lines.map((line) => (
                  <li key={line.seqNo} className="text-sm" data-speaker={line.speaker}>
                    {line.text}
                  </li>
                ))}
              </ul>
            )}
          </ScrollArea>
        </CardContent>
      ) : null}
    </Card>
  );
}
