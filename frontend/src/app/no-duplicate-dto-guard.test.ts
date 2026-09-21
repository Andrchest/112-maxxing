import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC_ROOT = join(process.cwd(), 'src');
// Types come only from the generated schema (D12 design decision #1) — no hand-written
// interface may duplicate an openapi schema shape.
const DTO_INTERFACE_PATTERN = /^\s*(?:export\s+)?interface\s+\w*(?:View|Request|Response)\b/m;

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith('.d.ts')) {
      files.push(full);
    }
  }
  return files;
}

// Guard for D12 design decision #1: a vitest scans src/ for `interface .*View|Request|Response`
// outside shared/api and fails. `schema.d.ts` (the generated file) and this guard itself are the
// only sanctioned exceptions.
describe('no hand-written DTO duplicates a generated openapi schema', () => {
  it('finds no interface named *View, *Request or *Response outside shared/api', () => {
    const offenders: string[] = [];

    for (const file of collectSourceFiles(SRC_ROOT)) {
      const relativePath = relative(SRC_ROOT, file);
      if (relativePath.startsWith(join('shared', 'api'))) {
        continue;
      }
      const source = readFileSync(file, 'utf-8');
      if (DTO_INTERFACE_PATTERN.test(source)) {
        offenders.push(relativePath);
      }
    }

    expect(offenders).toEqual([]);
  });
});
