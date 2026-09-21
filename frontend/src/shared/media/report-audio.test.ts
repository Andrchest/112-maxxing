import { describe, expect, it } from 'vitest';
import { isTranscriptSegmentPlaying, seekTargetForTranscriptSegment } from './report-audio';

const audioSegments = [
  { audio_segment_id: 'audio-1', start_ms: 1000, purged: false },
  { audio_segment_id: 'audio-2', start_ms: 5000, purged: false },
  { audio_segment_id: 'audio-3', start_ms: 9000, purged: true },
];

describe('seekTargetForTranscriptSegment', () => {
  it('returns the segment-relative offset in seconds', () => {
    expect(seekTargetForTranscriptSegment({ start_ms: 1500, audio_segment_id: 'audio-1' }, audioSegments)).toEqual({
      audioSegmentId: 'audio-1',
      offsetSeconds: 0.5,
    });
  });

  it('clamps a negative offset (data inconsistency) to zero rather than seeking backwards', () => {
    expect(seekTargetForTranscriptSegment({ start_ms: 800, audio_segment_id: 'audio-1' }, audioSegments)).toEqual({
      audioSegmentId: 'audio-1',
      offsetSeconds: 0,
    });
  });

  it('returns null when the transcript line has no linked audio segment', () => {
    expect(seekTargetForTranscriptSegment({ start_ms: 1500, audio_segment_id: null }, audioSegments)).toBeNull();
  });

  it('returns null when the referenced audio segment id is not in the list', () => {
    expect(seekTargetForTranscriptSegment({ start_ms: 1500, audio_segment_id: 'missing' }, audioSegments)).toBeNull();
  });

  it('returns null when the audio segment was purged (SPEC §41, D9)', () => {
    expect(seekTargetForTranscriptSegment({ start_ms: 9200, audio_segment_id: 'audio-3' }, audioSegments)).toBeNull();
  });
});

describe('isTranscriptSegmentPlaying', () => {
  const line = { start_ms: 5200, end_ms: 5800, audio_segment_id: 'audio-2' };

  it('is true while currentTime falls inside the line window of the active segment', () => {
    // audio-2 starts at session ms 5000; currentTime 0.5s -> session ms 5500, inside [5200, 5800).
    expect(isTranscriptSegmentPlaying(line, 'audio-2', 0.5, audioSegments)).toBe(true);
  });

  it('is false once currentTime moves past the line end', () => {
    expect(isTranscriptSegmentPlaying(line, 'audio-2', 1.2, audioSegments)).toBe(false);
  });

  it('is false for a different audio segment entirely', () => {
    expect(isTranscriptSegmentPlaying(line, 'audio-1', 0.5, audioSegments)).toBe(false);
  });

  it('is false while nothing is playing', () => {
    expect(isTranscriptSegmentPlaying(line, null, 0.5, audioSegments)).toBe(false);
  });
});
