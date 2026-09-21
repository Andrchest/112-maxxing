import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TranscriptAudioPanel } from './transcript-audio-panel';
import { ru } from '@/shared/i18n/ru';
import { makeAudioSegment, makeTranscriptSegment } from './test-fixtures';

// `TranscriptSegmentView.text` is ASR/TTS-generated free text; every fixture override below uses
// a non-Cyrillic placeholder only so the literal never trips `no-cyrillic-guard.test.ts` (which
// scans every .tsx source file, not just component code) — the component renders whatever the API
// returns verbatim, in Russian in production.
const CALLER_LINE = 'caller reports a fire';

// A string body, not a `Blob` one: jsdom's `Blob` polyfill (the global this test environment
// provides) lacks `.stream()`, which undici's `Response` constructor needs — a plain string body
// sidesteps that interop gap and still exercises `response.blob()` on the receiving end.
function blobResponse(status = 200): Response {
  return new Response('fake-wav-bytes', {
    status,
    headers: { 'content-type': 'audio/wav' },
  });
}

describe('TranscriptAudioPanel — click a transcript line, seek to the segment-relative offset', () => {
  // jsdom has no `URL.createObjectURL`/`revokeObjectURL` implementation — patched directly on the
  // class rather than via `vi.stubGlobal('URL', …)`, which would replace the constructor itself.
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('renders the empty state for an empty transcript', () => {
    render(<TranscriptAudioPanel sessionId="sess-1" transcript={[]} audioSegments={[]} />);
    expect(screen.getByText(ru.reportTranscriptEmpty)).toBeInTheDocument();
  });

  it('renders each transcript line with its speaker label', () => {
    render(
      <TranscriptAudioPanel
        sessionId="sess-1"
        transcript={[makeTranscriptSegment({ id: 't1', speaker: 'CALLER', text: CALLER_LINE })]}
        audioSegments={[makeAudioSegment()]}
      />,
    );
    expect(screen.getByText(CALLER_LINE)).toBeInTheDocument();
    expect(screen.getByText(ru.speakerCaller)).toBeInTheDocument();
  });

  it('fetches the linked audio segment on click and seeks to the segment-relative offset', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/api/v1/sessions/sess-1/audio/audio-1');
      return blobResponse();
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <TranscriptAudioPanel
        sessionId="sess-1"
        transcript={[makeTranscriptSegment({ id: 't1', text: CALLER_LINE, audio_segment_id: 'audio-1', start_ms: 1500 })]}
        audioSegments={[makeAudioSegment({ audio_segment_id: 'audio-1', start_ms: 1000 })]}
      />,
    );

    await user.click(screen.getByText(CALLER_LINE));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const audioEl = document.querySelector('audio') as HTMLAudioElement;
      expect(audioEl.currentTime).toBeCloseTo(0.5);
    });
  });

  it('shows the load-failure message when the audio fetch fails', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ title: 'Not Found', status: 404, code: 'NOT_FOUND' }), {
          status: 404,
          headers: { 'content-type': 'application/problem+json' },
        }),
      ),
    );

    render(
      <TranscriptAudioPanel
        sessionId="sess-1"
        transcript={[makeTranscriptSegment({ id: 't1', text: CALLER_LINE, audio_segment_id: 'audio-1', start_ms: 1500 })]}
        audioSegments={[makeAudioSegment({ audio_segment_id: 'audio-1', start_ms: 1000 })]}
      />,
    );

    await user.click(screen.getByText(CALLER_LINE));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('renders no seek control (a disabled line) when the audio was purged', () => {
    render(
      <TranscriptAudioPanel
        sessionId="sess-1"
        transcript={[makeTranscriptSegment({ id: 't1', text: CALLER_LINE, audio_segment_id: 'audio-1' })]}
        audioSegments={[makeAudioSegment({ audio_segment_id: 'audio-1', purged: true })]}
      />,
    );
    expect(screen.getByRole('button', { name: new RegExp(CALLER_LINE) })).toBeDisabled();
  });
});
