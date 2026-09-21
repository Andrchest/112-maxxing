// Pure reducer: folds one realtime `SessionEventEnvelope` onto the current `DdsWorkItem`
// (`docs/hld/10-domain-model.md` §10.13 payload catalog; D12 design decision #5's convergence
// pattern). Every patch below copies a value the event payload already carries verbatim — nothing
// here infers a status, a card fact or a resource-id list the backend did not send (SPEC §10, §42
// test 3). `HANDOFF_RECEIVED`'s payload (`snapshot_id`, `assignment_id`, `role_stage_id`,
// `service_type`, `at_offset_ms`) is not self-sufficient to build a whole new `DdsWorkItem`
// (missing `card_values`, `recipient_services`, `missing_field_paths`, ...) — the DDS console page
// re-fetches the snapshot on that event instead of folding it here, exactly as the operator
// console re-fetches on `STAGE_STATE_CHANGED` (see `STAGE_REFRESH...` sets in each console page).
//
// Idempotent by construction for every branch (set-membership add/remove, or an absolute
// overwrite) — applying the same event twice never changes the result a second time, matching
// `entities/card`'s `applyCardEvent` (no seq_no bookkeeping needed here either).
import type { DdsWorkItem, DDSStageState } from './work-item-store';
import type { components } from '@/shared/api';

type SessionEventEnvelope = components['schemas']['SessionEventEnvelope'];
type ClosureReason = components['schemas']['ClosureReason'];
type RoleType = components['schemas']['RoleType'];

interface DdsAcknowledgedPayload {
  assignment_id: string;
  at_offset_ms: number;
}
interface ResourceSelectedPayload {
  assignment_id: string;
  resource_id: string;
}
interface ResourceDeselectedPayload {
  assignment_id: string;
  resource_id: string;
}
interface ResourceDispatchedPayload {
  assignment_id: string;
  resource_ids: string[];
  at_offset_ms: number;
}
interface DdsIncidentClosedPayload {
  assignment_id: string;
  closure_reason: ClosureReason;
  at_offset_ms: number;
}
interface StageStateChangedPayload {
  role_stage_id: string;
  role_type: RoleType;
  new_state: string;
}

function dedupeAppend(ids: readonly string[], toAdd: readonly string[]): string[] {
  const set = new Set(ids);
  for (const id of toAdd) set.add(id);
  return Array.from(set);
}

function removeAll(ids: readonly string[], toRemove: readonly string[]): string[] {
  const removeSet = new Set(toRemove);
  return ids.filter((id) => !removeSet.has(id));
}

/** Folds one event onto `previous`. Returns `previous` unchanged for any event type this work
 * item does not react to, or when the event belongs to a different assignment/stage. */
export function applyWorkItemEvent(
  previous: DdsWorkItem | null,
  event: SessionEventEnvelope,
): DdsWorkItem | null {
  if (previous === null) {
    return previous;
  }
  switch (event.event_type) {
    case 'DDS_ACKNOWLEDGED': {
      const payload = event.payload as unknown as DdsAcknowledgedPayload;
      if (payload.assignment_id !== previous.assignment_id) return previous;
      return { ...previous, acknowledged_at_offset_ms: payload.at_offset_ms };
    }
    case 'RESOURCE_SELECTED': {
      const payload = event.payload as unknown as ResourceSelectedPayload;
      if (payload.assignment_id !== previous.assignment_id) return previous;
      return { ...previous, selected_resource_ids: dedupeAppend(previous.selected_resource_ids, [payload.resource_id]) };
    }
    case 'RESOURCE_DESELECTED': {
      const payload = event.payload as unknown as ResourceDeselectedPayload;
      if (payload.assignment_id !== previous.assignment_id) return previous;
      return { ...previous, selected_resource_ids: removeAll(previous.selected_resource_ids, [payload.resource_id]) };
    }
    case 'RESOURCE_DISPATCHED': {
      const payload = event.payload as unknown as ResourceDispatchedPayload;
      if (payload.assignment_id !== previous.assignment_id) return previous;
      return {
        ...previous,
        selected_resource_ids: removeAll(previous.selected_resource_ids, payload.resource_ids),
        dispatched_resource_ids: dedupeAppend(previous.dispatched_resource_ids, payload.resource_ids),
        dispatched_at_offset_ms: previous.dispatched_at_offset_ms ?? payload.at_offset_ms,
      };
    }
    case 'DDS_INCIDENT_CLOSED': {
      const payload = event.payload as unknown as DdsIncidentClosedPayload;
      if (payload.assignment_id !== previous.assignment_id) return previous;
      return { ...previous, closed_at_offset_ms: payload.at_offset_ms, closure_reason: payload.closure_reason };
    }
    case 'STAGE_STATE_CHANGED': {
      const payload = event.payload as unknown as StageStateChangedPayload;
      if (payload.role_type !== 'DDS' || payload.role_stage_id !== previous.role_stage_id) return previous;
      return { ...previous, state: payload.new_state as DDSStageState };
    }
    default:
      return previous;
  }
}
