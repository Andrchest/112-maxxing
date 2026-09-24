// The report's calls (I3 E6c backend: `call_id` / `call_party_ru` on `TimelineEntryView` and
// `TranscriptSegmentView`; rendered since E6d). Pure helpers shared by `timeline-section.tsx` and
// `transcript-audio-panel.tsx`, kept out of the component files for fast refresh.
import { t } from '@/shared/i18n';
import type { TimelineEntryView, TranscriptSegmentView } from '@/shared/api';

export interface CallOption {
  callId: string;
  partyRu: string;
}

/** The report's calls in order of first appearance, each with its party label. */
export function timelineCalls(timeline: readonly TimelineEntryView[]): CallOption[] {
  const calls = new Map<string, string | null>();
  for (const entry of timeline) {
    if (!entry.call_id) continue;
    if (!calls.has(entry.call_id) || (calls.get(entry.call_id) === null && entry.call_party_ru)) {
      calls.set(entry.call_id, entry.call_party_ru ?? null);
    }
  }
  return Array.from(calls, ([callId, partyRu]) => ({ callId, partyRu: partyRu ?? t('reportCallPartyUnknown') }));
}

export interface TranscriptGroup {
  /** The call's id, or `null` for the turns no call claims (and for a report without calls). */
  callId: string | null;
  partyRu: string | null;
  segments: TranscriptSegmentView[];
}

/** The transcript's turns grouped per call, in order of each call's first turn. */
export function groupTranscriptByCall(transcript: readonly TranscriptSegmentView[]): TranscriptGroup[] {
  const groups = new Map<string | null, TranscriptGroup>();
  for (const segment of transcript) {
    const callId = segment.call_id ?? null;
    let group = groups.get(callId);
    if (!group) {
      group = { callId, partyRu: segment.call_party_ru ?? null, segments: [] };
      groups.set(callId, group);
    }
    if (group.partyRu === null && segment.call_party_ru) group.partyRu = segment.call_party_ru;
    group.segments.push(segment);
  }
  return Array.from(groups.values());
}
