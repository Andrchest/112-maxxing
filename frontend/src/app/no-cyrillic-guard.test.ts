import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { findCyrillicLiterals } from '@/shared/lib/no-cyrillic-literals';

function collectTsxFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectTsxFiles(full));
    } else if (entry.isFile() && entry.name.endsWith('.tsx')) {
      files.push(full);
    }
  }
  return files;
}

// Guard for D12: no .tsx file under src/app or src/features may contain a
// hard-coded Cyrillic string literal or JSX text node. All trainee-facing
// text must come from src/shared/i18n/ru.ts through t().
describe('no hard-coded Cyrillic UI strings', () => {
  const scanRoots = [join(process.cwd(), 'src/app'), join(process.cwd(), 'src/features')];

  it('finds no Cyrillic literal in any src/app or src/features .tsx file', () => {
    const offenders: { file: string; hits: string[] }[] = [];

    for (const root of scanRoots) {
      for (const file of collectTsxFiles(root)) {
        const hits = findCyrillicLiterals(readFileSync(file, 'utf-8'));
        if (hits.length > 0) {
          offenders.push({ file, hits });
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
