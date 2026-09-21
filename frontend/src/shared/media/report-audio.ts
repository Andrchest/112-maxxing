// The report's click-transcript-to-seek helper (SPEC §29 item 7; D9, D12). Pure — no fetch, no
// DOM, no `<audio>` element — so it is unit-tested on its own; `features/report/transcript-audio-
// panel.tsx` is the only caller and owns the actual `getAudioSegment` fetch + object-URL
// lifecycle (D12 design decision #2: this module never touches the network).
//
// Both `TranscriptSegmentView.start_ms` and `AudioSegmentRef.start_ms` are session-relative
// (`docs/hld/openapi.yaml`: "Session-relative, not file-relative", D9) — the segment-relative
// offset an `<audio>` element's `currentTime` needs is simply the difference between the two,
// clamped to zero so a data inconsistency never seeks negative.
export interface SeekTarget {
  audioSegmentId: string;
  /** `<audio>.currentTime`-ready offset, in seconds, from the start of that one audio segment. */
  offsetSeconds: number;
}

export interface SeekableTranscriptSegment {
  start_ms: number;
  audio_segment_id: string | null;
}

export interface SeekableAudioSegment {
  audio_segment_id: string;
  start_ms: number;
  purged: boolean;
}

/**
 * Resolves which audio segment to load and where to seek within it for a clicked transcript
 * line. `null` when the line has no linked audio (`audio_segment_id === null`, e.g. it was
 * never recorded), the referenced audio segment is not in `audioSegments` (data inconsistency),
 * or the audio was purged by the retention policy (SPEC §41, D9) — the transcript still renders,
 * playback just cannot start.
 */
export function seekTargetForTranscriptSegment(
  transcriptSegment: SeekableTranscriptSegment,
  audioSegments: readonly SeekableAudioSegment[],
): SeekTarget | null {
  if (transcriptSegment.audio_segment_id === null) {
    return null;
  }
  const audioSegment = audioSegments.find((segment) => segment.audio_segment_id === transcriptSegment.audio_segment_id);
  if (!audioSegment || audioSegment.purged) {
    return null;
  }
  const offsetMs = Math.max(0, transcriptSegment.start_ms - audioSegment.start_ms);
  return { audioSegmentId: audioSegment.audio_segment_id, offsetSeconds: offsetMs / 1000 };
}

/** Whether `currentTimeSeconds` (an `<audio>` element's live `currentTime` while
 * `activeAudioSegmentId` is playing) falls inside one transcript line's `[start_ms, end_ms)`
 * window — used to highlight "the currently playing line" (SPEC §29 item 7). */
export function isTranscriptSegmentPlaying(
  transcriptSegment: SeekableTranscriptSegment & { end_ms: number },
  activeAudioSegmentId: string | null,
  currentTimeSeconds: number,
  audioSegments: readonly SeekableAudioSegment[],
): boolean {
  if (activeAudioSegmentId === null || transcriptSegment.audio_segment_id !== activeAudioSegmentId) {
    return false;
  }
  const audioSegment = audioSegments.find((segment) => segment.audio_segment_id === activeAudioSegmentId);
  if (!audioSegment) {
    return false;
  }
  const currentSessionMs = audioSegment.start_ms + currentTimeSeconds * 1000;
  return currentSessionMs >= transcriptSegment.start_ms && currentSessionMs < transcriptSegment.end_ms;
}
