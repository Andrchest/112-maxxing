// Pure reducer: folds one realtime `SessionEventEnvelope` onto the current resource board
// (D12 design decision #5's convergence pattern, applied to the DDS resource board). Resource
// movement (`depart`, `arrive`, `start_work`, `finish_work`, `return_to_base`, `breakdown`,
// `repair`, `make_unavailable`, `make_available`) is driven by `SIMULATION` on a timer, not a
// trainee command — `RESOURCE_STATUS_CHANGED` (`docs/hld/10-domain-model.md` §10.7's
// `RESOURCE_STATUS_TRANSITIONS`: "every fired transition emits `RESOURCE_STATUS_CHANGED`") is the
// *only* event that carries the new `current_status` verbatim, so it is the only one this reducer
// folds. `RESOURCE_SELECTED`/`RESOURCE_DESELECTED`/`RESOURCE_DISPATCHED` are folded onto the work
// item's `selected_resource_ids`/`dispatched_resource_ids` instead (`entities/work-item`) — a
// select/deselect/dispatch command also always emits its own `RESOURCE_STATUS_CHANGED`
// (`select`->SELECTED, `deselect`->AVAILABLE, `dispatch`/`dispatch_additional`->DISPATCHED), so
// this reducer never needs to infer a status from an event that does not carry one.
//
// Applying the same `RESOURCE_STATUS_CHANGED` twice is a no-op — it overwrites `current_status`
// with the same `new_status` again — idempotent by construction, no seq_no bookkeeping needed here
// (the session-events store already de-dupes by seq_no for the log itself).
import type { EmergencyResourceView, ResourceStatus } from './resource-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];

interface ResourceStatusChangedPayload {
  resource_id: string;
  new_status: ResourceStatus;
}

/** Folds one event onto `previous`. Returns `previous` unchanged (same array reference) for any
 * event type or `resource_id` this board does not react to. */
export function applyResourceEvent(
  previous: EmergencyResourceView[],
  event: SessionEventEnvelope,
): EmergencyResourceView[] {
  if (event.event_type !== 'RESOURCE_STATUS_CHANGED') {
    return previous;
  }
  const payload = event.payload as unknown as ResourceStatusChangedPayload;
  const index = previous.findIndex((resource) => resource.resource_id === payload.resource_id);
  if (index === -1) {
    return previous;
  }
  const next = previous.slice();
  next[index] = { ...next[index]!, current_status: payload.new_status };
  return next;
}
