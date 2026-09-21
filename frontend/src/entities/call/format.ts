// Pure display formatting for the phone widget's call timer (SPEC §32: "the call is a phone
// widget ... timer"). Takes only values the server already sent (`CallStateView` offsets) —
// never a client-side guess at simulation time.
export function formatCallDurationMs(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
