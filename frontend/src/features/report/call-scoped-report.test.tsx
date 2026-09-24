import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TimelineSection } from './timeline-section';
import { TranscriptAudioPanel } from './transcript-audio-panel';
import { groupTranscriptByCall, timelineCalls } from './call-groups';
import { ru } from '@/shared/i18n/ru';
import { makeAudioSegment, makeTimelineEntry, makeTranscriptSegment } from './test-fixtures';

// The report's calls (I3 E6c backend: `call_id` / `call_party_ru` on timeline and transcript rows;
// rendered since E6d). Party labels and texts are server-generated Russian in production; the
// fixtures use non-Cyrillic placeholders so `no-cyrillic-guard.test.ts` stays green.
const CALL_112 = 'call-112';
const DDS_TO_112 = 'call-dds-112';
const PARTY_112 = 'Call 112: caller';
const PARTY_DDS = 'DDS call: operator 112';

describe('The report groups a session calls (I3 E6d)', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    URL.revokeObjectURL = vi.fn();
  });

  it('labels each call entry of the timeline with its party and filters by call', async () => {
    const user = userEvent.setup();
    const timeline = [
      makeTimelineEntry({ seq_no: 1, summary_ru: 'session started' }),
      makeTimelineEntry({ seq_no: 2, summary_ru: 'caller speaks', call_id: CALL_112, call_party_ru: PARTY_112 }),
      makeTimelineEntry({ seq_no: 3, summary_ru: 'dds dials 112', call_id: DDS_TO_112, call_party_ru: PARTY_DDS }),
      makeTimelineEntry({ seq_no: 4, summary_ru: 'operator asks', call_id: DDS_TO_112, call_party_ru: PARTY_DDS }),
    ];
    expect(timelineCalls(timeline)).toEqual([
      { callId: CALL_112, partyRu: PARTY_112 },
      { callId: DDS_TO_112, partyRu: PARTY_DDS },
    ]);
    render(<TimelineSection timeline={timeline} />);
    const row = screen.getByText('operator asks').closest('li');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(PARTY_DDS)).toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: ru.reportTimelineCallFilterLabel }), DDS_TO_112);
    expect(screen.getByText('dds dials 112')).toBeInTheDocument();
    expect(screen.getByText('operator asks')).toBeInTheDocument();
    expect(screen.queryByText('caller speaks')).toBeNull();
    expect(screen.queryByText('session started')).toBeNull();
  });

  it('renders a timeline without calls as before: no call filter, no party label', () => {
    render(<TimelineSection timeline={[makeTimelineEntry({ seq_no: 1, summary_ru: 'session started' })]} />);
    expect(screen.queryByRole('combobox', { name: ru.reportTimelineCallFilterLabel })).toBeNull();
    expect(screen.getByText('session started')).toBeInTheDocument();
  });

  it('groups the transcript per call under its party label, in the order the calls speak', () => {
    const transcript = [
      makeTranscriptSegment({ id: 't1', text: 'line one', call_id: CALL_112, call_party_ru: PARTY_112 }),
      makeTranscriptSegment({ id: 't2', speaker: 'OPERATOR', text: 'line two', call_id: DDS_TO_112, call_party_ru: PARTY_DDS }),
      makeTranscriptSegment({ id: 't3', text: 'line three', call_id: CALL_112, call_party_ru: PARTY_112 }),
    ];
    expect(groupTranscriptByCall(transcript).map((group) => [group.callId, group.partyRu, group.segments.map((s) => s.id)])).toEqual([
      [CALL_112, PARTY_112, ['t1', 't3']],
      [DDS_TO_112, PARTY_DDS, ['t2']],
    ]);
    const { container } = render(<TranscriptAudioPanel sessionId="sess-1" transcript={transcript} audioSegments={[makeAudioSegment()]} />);
    const headings = Array.from(container.querySelectorAll('[data-slot="transcript-call-heading"]')).map((node) => node.textContent);
    expect(headings).toEqual([PARTY_112, PARTY_DDS]);
    const groups = container.querySelectorAll('[data-slot="transcript-call-group"]');
    expect(within(groups[0] as HTMLElement).getByText('line three')).toBeInTheDocument();
    expect(within(groups[1] as HTMLElement).getByText('line two')).toBeInTheDocument();
  });

  it('renders a transcript without calls as one list with no heading', () => {
    const { container } = render(
      <TranscriptAudioPanel sessionId="sess-1" transcript={[makeTranscriptSegment({ id: 't1', text: 'line one' })]} audioSegments={[makeAudioSegment()]} />,
    );
    expect(container.querySelectorAll('[data-slot="transcript-call-heading"]')).toHaveLength(0);
    expect(screen.getByText('line one')).toBeInTheDocument();
    expect(screen.getByText(ru.speakerCaller)).toBeInTheDocument();
  });
});
