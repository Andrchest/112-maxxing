// Guard for D3/SPEC §42 test 3: the DDS console can never show operator-card-live data,
// transcript or world truth. Parses the generated `schema.d.ts` source (not the TS type system —
// this must catch a leak even if nothing in `src/` happens to reference the offending property
// yet) and asserts none of the DDS-facing schemas carries a property named like world truth,
// caller belief or hidden gate internals. This is the E10 epic-list row's own required test.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SCHEMA_PATH = join(process.cwd(), 'src/shared/api/schema.d.ts');
const SCHEMA_SOURCE = readFileSync(SCHEMA_PATH, 'utf-8');

// Matches "<indent>SomeName: {" through the next same-or-lower-indent "};" close — good enough
// for the generated, consistently-indented openapi-typescript output this repo produces.
function extractInterfaceBody(schemaName: string): string {
  const startPattern = new RegExp(`^( +)${schemaName}: \\{\\n`, 'm');
  const startMatch = startPattern.exec(SCHEMA_SOURCE);
  if (!startMatch) {
    throw new Error(`schema.d.ts has no "${schemaName}" property under components.schemas`);
  }
  const indent = startMatch[1]!;
  const bodyStart = startMatch.index + startMatch[0].length;
  const closeLine = `${indent}};`;
  const closeIndex = SCHEMA_SOURCE.indexOf(`\n${closeLine}`, bodyStart);
  if (closeIndex === -1) {
    throw new Error(`could not find the closing brace for "${schemaName}" in schema.d.ts`);
  }
  return SCHEMA_SOURCE.slice(bodyStart, closeIndex);
}

// Property names only — "world_events: components[...]" declares a property, a doc-comment
// mentioning "world" in prose does not. `openapi-typescript` renders each property as
// `<indent>property_name?: type;` (optionally preceded by a JSDoc block), so this only looks at
// identifier-like tokens directly followed by `?:` or `:`.
const PROPERTY_LINE = /^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\??:\s/gm;
// `world_event` (unanchored) also catches `source_world_event_id` — the hidden world event that
// produced a notification or a radio message. It is not a world *value*, but it names the
// scenario's hidden world event, which is exactly what INV 3 keeps out of trainee bytes; the WS
// path already redacts it (`backend/app/application/realtime/redaction.py`, HLD 40 §215-239) and
// since E20 the REST list schemas do not declare it either.
const FORBIDDEN_NAME = /^world_|^caller_|world_event|hidden|truth/i;

// Named outright so a future schema edit that reintroduces one of these is a red test with an
// unambiguous message, not just an empty-array mismatch.
const FORBIDDEN_EXACT_NAMES = ['source_world_event_id', 'world_event'] as const;

function forbiddenPropertyNames(body: string): string[] {
  const offenders: string[] = [];
  for (const match of body.matchAll(PROPERTY_LINE)) {
    const name = match[1]!;
    if (FORBIDDEN_NAME.test(name)) {
      offenders.push(name);
    }
  }
  return offenders;
}

describe('DDS-facing schemas never carry world truth / caller belief / hidden gate internals (D3, SPEC §42 test 3)', () => {
  it.each(['DdsWorkItem', 'DdsStageView', 'EmergencyResourceView', 'NotificationView', 'RadioMessageView'])(
    '%s has no world_*/caller_*/truth/hidden property',
    (schemaName) => {
      const body = extractInterfaceBody(schemaName);
      // Only this schema's own top-level properties — not the types they reference (e.g.
      // `EmergencyResourceView[]`), so a *different* schema's own world/caller fields elsewhere in
      // the file are not what this assertion is about.
      const topLevelBody = body.replace(/\{[\s\S]*?\}/g, '{}');
      expect(forbiddenPropertyNames(topLevelBody)).toEqual([]);
    },
  );

  it.each(['NotificationView', 'RadioMessageView'])(
    '%s declares neither source_world_event_id nor world_event (INV 3, REST path)',
    (schemaName) => {
      const topLevelBody = extractInterfaceBody(schemaName).replace(/\{[\s\S]*?\}/g, '{}');
      const declared = [...topLevelBody.matchAll(PROPERTY_LINE)].map((match) => match[1]!);
      for (const forbidden of FORBIDDEN_EXACT_NAMES) {
        expect(declared, `${schemaName} must not declare ${forbidden}`).not.toContain(forbidden);
      }
    },
  );
});
