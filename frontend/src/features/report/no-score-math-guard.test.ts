// Guard for the epic row's own invariant ("it may not alter numeric results", SPEC §2/§29; D11):
// no file under features/report computes a total from the score results itself — every number
// the report shows (total_points, by_category, evidence points) is displayed exactly as
// `getSessionReport` returned it. Mirrors `features/dds/no-world-truth-guard.test.ts`'s approach
// of scanning the actual source text rather than relying on the type system to catch a leak.
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const REPORT_ROOT = join(process.cwd(), 'src/features/report');

// `.reduce(` (array summation) and `points_awarded +`/`+= points` (manual accumulation) are the
// two shapes a re-aggregation would take; a `.map`/`.filter` alone never adds numbers together.
const FORBIDDEN_PATTERNS: RegExp[] = [/\.reduce\(/, /total_points\s*\+=?/, /points_awarded\s*\+/, /\bsum\s*\(/i];

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith('.test.ts') && !entry.name.endsWith('.test.tsx')) {
      files.push(full);
    }
  }
  return files;
}

describe('no file under features/report re-aggregates score numbers (SPEC §2/§29, D11)', () => {
  it('finds no .reduce(/manual points accumulation over score results', () => {
    const offenders: { file: string; hits: string[] }[] = [];

    for (const file of collectSourceFiles(REPORT_ROOT)) {
      // This guard file itself would otherwise match its own pattern list.
      if (file.endsWith('no-score-math-guard.test.ts')) continue;
      const source = readFileSync(file, 'utf-8');
      const hits = FORBIDDEN_PATTERNS.filter((pattern) => pattern.test(source)).map((pattern) => pattern.source);
      if (hits.length > 0) {
        offenders.push({ file: relative(process.cwd(), file), hits });
      }
    }

    expect(offenders).toEqual([]);
  });
});
