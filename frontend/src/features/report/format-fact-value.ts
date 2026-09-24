// `final-card-section.tsx` has imported `formatFactValueRu` from this file's name since before I3
// E3c; kept as a thin re-export so that import stays valid. The actual schema-driven formatter —
// options, the v1 enum-value fallback, `recipients.services` — lives in `snapshot-card-fields.ts`
// now, the one copy `handoff-section.tsx` shares too (there is no longer a second copy of the
// enum-value table here).
export { formatCardValueRu as formatFactValueRu } from './snapshot-card-fields';
