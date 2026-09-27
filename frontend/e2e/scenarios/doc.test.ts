// I6 SCENARIOS: the committed text in `docs/test-scenarios/` must be exactly what `doc.ts` renders
// from the scenario definitions the runner executes — so the text a tester follows is the text the
// runner proved on a stand. After changing a definition: `make e2e-scenarios-doc` (sets
// SCENARIO_DOC_WRITE=1, which rewrites the files instead of comparing).
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderAll } from './doc';
import { ALL_SCENARIOS } from './index';

// vitest runs from `frontend/` (its config's root); the text lives in the repo's `docs/`.
const DOC_DIR = path.resolve(process.cwd(), '..', 'docs', 'test-scenarios');

describe('docs/test-scenarios (I6 SCENARIOS)', () => {
  const rendered = renderAll(ALL_SCENARIOS);

  if (process.env.SCENARIO_DOC_WRITE === '1') {
    it('rewrites the text from the definitions', () => {
      mkdirSync(DOC_DIR, { recursive: true });
      for (const name of readdirSync(DOC_DIR)) if (name.endsWith('.md') && !rendered.has(name)) rmSync(path.join(DOC_DIR, name));
      for (const [name, content] of rendered) writeFileSync(path.join(DOC_DIR, name), content);
      expect(readdirSync(DOC_DIR).filter((name) => name.endsWith('.md')).sort()).toEqual([...rendered.keys()].sort());
    });
    return;
  }

  it('has exactly one file per scenario plus the instructions', () => {
    const present = readdirSync(DOC_DIR).filter((name) => name.endsWith('.md')).sort();
    expect(present).toEqual([...rendered.keys()].sort());
  });

  for (const [name, content] of rendered) {
    it(`${name} is up to date with the definitions (make e2e-scenarios-doc)`, () => {
      expect(readFileSync(path.join(DOC_DIR, name), 'utf8')).toBe(content);
    });
  }

  it('numbers every step SNN.MM, unique across the set', () => {
    const ids = ALL_SCENARIOS.flatMap((scenario) => scenario.steps.map((step) => step.id));
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^S\d\d\.\d\d$/);
  });

  it('gives every step an instruction and at least one thing to see', () => {
    for (const scenario of ALL_SCENARIOS) {
      for (const step of scenario.steps) {
        expect(step.do.trim(), step.id).not.toBe('');
        expect(step.expect.length, step.id).toBeGreaterThan(0);
      }
    }
  });
});
