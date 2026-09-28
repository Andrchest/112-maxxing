// I6 SCENARIOS: the committed text in `docs/test-scenarios/` must be exactly what `doc.ts` renders
// from the scenario definitions the runner executes — so the text a tester follows is the text the
// runner proved on a stand. After changing a definition: `make e2e-scenarios-doc` (sets
// SCENARIO_DOC_WRITE=1, which rewrites the files instead of comparing).
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderAll, scenarioFileName } from './doc';
import { ALL_SCENARIOS } from './index';

// vitest runs from `frontend/` (its config's root); the text lives in the repo's `docs/`.
const DOC_DIR = path.resolve(process.cwd(), '..', 'docs', 'test-scenarios');

describe('docs/test-scenarios (I6 SCENARIOS)', () => {
  const rendered = renderAll(ALL_SCENARIOS);

  // I6 HTTP: build-bundle.sh --http asks for the http-only variant (secureOnly steps dropped)
  // written to SCENARIO_DOC_HTTP_DIR instead of docs/test-scenarios — that directory stays the
  // one canonical, committed rendering.
  if (process.env.SCENARIO_DOC_WRITE_HTTP === '1') {
    it('writes the http-only variant (secureOnly steps omitted)', () => {
      const outDir = process.env.SCENARIO_DOC_HTTP_DIR;
      if (!outDir) throw new Error('SCENARIO_DOC_HTTP_DIR is not set');
      const renderedHttp = renderAll(ALL_SCENARIOS, { omitSecureOnly: true });
      mkdirSync(outDir, { recursive: true });
      for (const name of readdirSync(outDir)) if (name.endsWith('.md') && !renderedHttp.has(name)) rmSync(path.join(outDir, name));
      for (const [name, content] of renderedHttp) writeFileSync(path.join(outDir, name), content);
      expect(readdirSync(outDir).filter((name) => name.endsWith('.md')).sort()).toEqual([...renderedHttp.keys()].sort());
    });
    return;
  }

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

  // I6 HTTP: every secureOnly step is marked in the committed (https) text and dropped from the
  // http variant, without moving any other step's id (ids come from position at `scenario()`,
  // before this filter ever runs).
  it('marks every secureOnly step «(только https)» and omits exactly those from the http variant', () => {
    const httpRendered = renderAll(ALL_SCENARIOS, { omitSecureOnly: true });
    const secureOnlyCount = ALL_SCENARIOS.flatMap((scenario) => scenario.steps).filter((step) => step.secureOnly).length;
    expect(secureOnlyCount).toBeGreaterThan(0);
    for (const scenario of ALL_SCENARIOS) {
      const content = rendered.get(scenarioFileName(scenario)) ?? '';
      const httpContent = httpRendered.get(scenarioFileName(scenario)) ?? '';
      for (const step of scenario.steps) {
        if (step.secureOnly) {
          expect(content, step.id).toContain(`| ${step.id} |`);
          expect(content, step.id).toMatch(new RegExp(`\\| ${step.id} \\|[^\\n]*\\(только https\\)`));
          expect(httpContent, step.id).not.toContain(`| ${step.id} |`);
        } else {
          expect(httpContent, step.id).toContain(`| ${step.id} |`);
        }
      }
    }
  });
});
