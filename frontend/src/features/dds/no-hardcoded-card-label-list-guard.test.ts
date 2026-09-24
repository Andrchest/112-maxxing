// Guard for the E3c row of `docs/hld/90-tbd-epics.md` ("vitest: no hard-coded card label list
// remains — grep test") and CHANGE 2 of its brief: since I3 E3a′/E3c, every field's `label_ru`
// (and, for v2, every option's `label_ru`) comes from the server's `field_specs` — no
// `field_path -> label` catalog belongs under `features/dds` or `features/report` any more. The
// two pre-E3c static field lists (the DDS side's and the report side's own copies of `CARD_FIELDS`)
// are both gone. Mirrors `no-score-math-guard.test.ts`'s approach of scanning the actual source
// text; the DDS side's deleted field-label file itself is checked separately by this epic's own
// CHECK command (a plain `test -e`), not duplicated here.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SCAN_ROOTS = [join(process.cwd(), 'src/features/dds'), join(process.cwd(), 'src/features/report')];
const THIS_FILE = join(process.cwd(), 'src/features/dds/no-hardcoded-card-label-list-guard.test.ts');

// Fingerprints of the pre-E3c field-path -> label catalogs: the two static field lists that
// duplicated `CARD_FIELDS`/`v2.yaml` by hand, and the `cardField*` ru.ts keys only those two
// catalogs ever used. `cardField[A-Z]` (lowercase `c`) never matches the `CardFieldSpec` type name
// (capital `C`).
const FORBIDDEN_PATTERNS: RegExp[] = [/\bDDS_CARD_FIELDS\b/, /\bSNAPSHOT_CARD_FIELDS\b/, /\bcardField[A-Z]\w*/];

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

describe('no hard-coded field_path -> label card catalog remains (I3 E3c, HLD 70 §70.5.4, D17)', () => {
  it('finds no DDS_CARD_FIELDS/SNAPSHOT_CARD_FIELDS/cardField* catalog under features/dds or features/report', () => {
    const offenders: { file: string; hits: string[] }[] = [];

    for (const root of SCAN_ROOTS) {
      for (const file of collectSourceFiles(root)) {
        if (file === THIS_FILE) continue;
        const source = readFileSync(file, 'utf-8');
        const hits = FORBIDDEN_PATTERNS.filter((pattern) => pattern.test(source)).map((pattern) => pattern.source);
        if (hits.length > 0) {
          offenders.push({ file: relative(process.cwd(), file), hits });
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
