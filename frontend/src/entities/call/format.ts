// Pure display formatting for the phone widget's call timer (SPEC §32: "the call is a phone
// widget ... timer"). Takes only values the server already sent (`CallStateView` offsets) —
// never a client-side guess at simulation time.
export function formatCallDurationMs(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/** A ДДС call's dialled number for display (I3 E6b): `+7 (916) 123-45-67` for an 11-digit
 * Russian number, the digits as the server sent them otherwise (`101`, `112`, `7012`). */
export function formatDialedRu(dialed: string): string {
  const digits = dialed.replace(/\D/g, '');
  if (digits.length !== 11) return dialed;
  const national = digits.slice(1);
  return `+7 (${national.slice(0, 3)}) ${national.slice(3, 6)}-${national.slice(6, 8)}-${national.slice(8, 10)}`;
}
