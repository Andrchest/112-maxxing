// The latest `RECIPIENTS_RESOLVED` of a session log (I3 E2b′, HLD 70 §70.6.4) — the services panel's
// «авто» marking. Pure over server events: nothing here resolves anything itself.
import type { ServiceId, SessionEventEnvelope } from '@/shared/api';

export interface Resolution {
  seqNo: number;
  auto: ServiceId[];
  informed: ServiceId[];
}

/** The latest `RECIPIENTS_RESOLVED` of `events` (by `seq_no`, whatever their order), or `null`. */
export function latestResolution(events: readonly SessionEventEnvelope[]): Resolution | null {
  let latest: Resolution | null = null;
  for (const event of events) {
    if (event.event_type !== 'RECIPIENTS_RESOLVED') continue;
    if (latest !== null && event.seq_no < latest.seqNo) continue;
    const payload = event.payload as { auto_services?: ServiceId[]; informed_services?: ServiceId[] };
    latest = {
      seqNo: event.seq_no,
      auto: payload.auto_services ?? [],
      informed: payload.informed_services ?? [],
    };
  }
  return latest;
}
