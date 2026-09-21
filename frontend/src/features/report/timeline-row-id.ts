// Shared between `timeline-section.tsx` (which renders the row) and `report-page.tsx` (which
// scrolls to it from `RuleEvidenceSection`'s "jump to event" button, §29 item 14). Kept out of
// `timeline-section.tsx` itself so that file only exports the component (Fast Refresh, eslint
// `react-refresh/only-export-components`).
export function timelineEntryRowId(seqNo: number): string {
  return `report-timeline-entry-${seqNo}`;
}
