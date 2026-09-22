import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC_ROOT = join(process.cwd(), 'src');

// D3/D11/R4: `WorldTruthView`/`CallerBeliefView` are exposed to the frontend ONLY in the
// instructor live overview (`features/instructor/**`) and the report's truth-vs-card diff
// (`features/report/truth-diff*`, D11: "the one place WorldTruth is shown to a human"). Every
// other file imports the redacted, trainee-facing views instead — a file importing either type
// name here is a structural leak, not a display choice.
const RESTRICTED_TYPE_NAMES = ['WorldTruthView', 'CallerBeliefView'];
const TYPE_NAME_PATTERN = new RegExp(`\\b(?:${RESTRICTED_TYPE_NAMES.join('|')})\\b`);

// Files allowed to name these types: their own declaration/generation, and the two sanctioned
// consumers. This guard file itself is the third sanctioned exception (same treatment
// `no-duplicate-dto-guard.test.ts` gives itself) — it names both types in its own source to build
// the pattern it scans for.
const ALLOWED_PATH_PREFIXES = [join('shared', 'api'), join('features', 'instructor'), join('features', 'report', 'truth-diff')];
const SELF_PATH = join('app', 'no-world-truth-guard.test.ts');

function isAllowed(relativePath: string): boolean {
  return relativePath === SELF_PATH || ALLOWED_PATH_PREFIXES.some((prefix) => relativePath.startsWith(prefix));
}

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

describe('no file outside features/instructor/** and features/report/truth-diff* names WorldTruthView/CallerBeliefView', () => {
  it('finds no offending reference', () => {
    const offenders: string[] = [];

    for (const file of collectSourceFiles(SRC_ROOT)) {
      const relativePath = relative(SRC_ROOT, file);
      if (isAllowed(relativePath)) {
        continue;
      }
      const source = readFileSync(file, 'utf-8');
      if (TYPE_NAME_PATTERN.test(source)) {
        offenders.push(relativePath);
      }
    }

    expect(offenders).toEqual([]);
  });
});
