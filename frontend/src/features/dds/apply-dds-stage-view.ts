// Every `/dds/*` command returns a `DdsStageView` (D8) — this is "the view is replaced by the
// server's response" (D12 design decision #1) applied consistently across every DDS command
// component: it writes `entities/work-item` (role_stage_id, work_item, available_actions,
// session_state, last_seq_no) and `entities/resource` (the resource board) from the one response,
// so no component re-implements the split by hand.
import { useWorkItemStore } from '@/entities/work-item';
import { useResourceStore } from '@/entities/resource';
import type { DdsStageView } from '@/shared/api';

export function applyDdsStageView(view: DdsStageView): void {
  useWorkItemStore.getState().setFromStageView(view);
  useResourceStore.getState().setResources(view.resources);
}
