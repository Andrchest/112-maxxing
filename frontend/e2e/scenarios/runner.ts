// I6 SCENARIOS: executes one scenario against a running stand, fail-fast. Steps run in order; the
// FIRST action error or unmet expectation stops the scenario and marks it СЛОМАН with the step id,
// the step's «Что сделать», the expectation that was not seen, a screenshot and the page address.
// Cleanups registered by the steps run afterwards either way (best effort, through the REST API).
import { expect, request, type Browser, type BrowserContext, type Page } from '@playwright/test';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import type { CleanupApi, Credentials, Download, Scenario, ScenarioContext } from './dsl';

/** «Моментально»: how long anything listed under «Должно быть видно» may take to show up. */
export const DEFAULT_TIMEOUT_MS = 5_000;
/** Page loads over the tailnet (a navigation, not a visibility check). */
export const NAVIGATION_TIMEOUT_MS = 15_000;

export interface RunnerEnv {
  baseUrl: string;
  resultsDir: string;
  accounts: Record<'admin' | 'instructor' | 'trainee', Credentials>;
}

export interface ScenarioResult {
  id: string;
  title: string;
  status: 'РАБОТАЕТ' | 'СЛОМАН';
  stepsTotal: number;
  stepsPassed: number;
  /** I6 HTTP: steps skipped because `E2E_SKIP_SECURE_ONLY=1` and `step.secureOnly` (the http
   * demo has no phone/microphone) — 0 in the ordinary https run. */
  stepsSkipped: number;
  durationMs: number;
  failure?: {
    stepId: string;
    do: string;
    notSeen: string;
    error: string;
    screenshot: string | null;
    url: string;
  };
  cleanup: { label: string; ok: boolean; error?: string }[];
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`переменная окружения ${name} не задана`);
  return value;
}

export function runnerEnvFromProcess(): RunnerEnv {
  return {
    baseUrl: required('E2E_BASE_URL').replace(/\/$/, ''),
    resultsDir: required('E2E_RESULTS_DIR'),
    accounts: {
      admin: { username: required('E2E_ADMIN_USER'), password: required('E2E_ADMIN_PASS') },
      instructor: { username: required('E2E_INSTRUCTOR_USER'), password: required('E2E_INSTRUCTOR_PASS') },
      trainee: { username: required('E2E_TRAINEE_USER'), password: required('E2E_TRAINEE_PASS') },
    },
  };
}

/** Base36 of a decreasing clock plus two random chars: unique, and a newer run sorts first. */
export function uniqueSuffix(): string {
  const reverse = 4_000_000_000 - Math.floor(Date.now() / 1000);
  return `${reverse.toString(36)}${Math.floor(Math.random() * 1296).toString(36).padStart(2, '0')}`;
}

const ANSI_COLOUR = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, 'g');

function firstLine(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  // Playwright's messages carry ANSI colours and a long call log; the first lines say it all.
  return message
    .replace(ANSI_COLOUR, '')
    .split('\n')
    .filter((line) => line.trim() !== '')
    .slice(0, 3)
    .join(' | ');
}

class Api implements CleanupApi {
  private readonly env: RunnerEnv;

  constructor(env: RunnerEnv) {
    this.env = env;
  }

  private async client(who: Credentials) {
    const anonymous = await request.newContext({ baseURL: this.env.baseUrl });
    const login = await anonymous.post('/api/v1/auth/login', { data: who });
    if (!login.ok()) throw new Error(`вход ${who.username} через API: ${login.status()}`);
    const token = ((await login.json()) as { access_token: string }).access_token;
    await anonymous.dispose();
    return request.newContext({ baseURL: this.env.baseUrl, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  }

  async blockUser(username: string): Promise<void> {
    const api = await this.client(this.env.accounts.admin);
    try {
      for (let offset = 0; offset < 5000; offset += 200) {
        const page = await api.get(`/api/v1/users?include_inactive=true&limit=200&offset=${offset}`);
        const body = (await page.json()) as { items: { id: string; username: string; is_active: boolean }[]; total: number };
        const user = body.items.find((item) => item.username === username);
        if (user) {
          if (user.is_active) {
            const response = await api.patch(`/api/v1/admin/users/${user.id}`, { data: { is_active: false } });
            if (!response.ok()) throw new Error(`блокировка ${username}: ${response.status()}`);
          }
          return;
        }
        if (offset + 200 >= body.total) return;
      }
    } finally {
      await api.dispose();
    }
  }

  async abortLesson(lessonId: string, owner: Credentials): Promise<void> {
    const api = await this.client(owner);
    try {
      const lesson = (await (await api.get(`/api/v1/lessons/${lessonId}`)).json()) as { state?: string };
      if (lesson.state !== 'CREATED' && lesson.state !== 'ACTIVE') return;
      const response = await api.post(`/api/v1/lessons/${lessonId}/abort`, { data: { reason: 'e2e: уборка после сценария' } });
      if (!response.ok()) throw new Error(`прерывание занятия: ${response.status()}`);
    } finally {
      await api.dispose();
    }
  }

  async unarchiveScenario(title: string): Promise<void> {
    const api = await this.client(this.env.accounts.instructor);
    try {
      const list = (await (await api.get('/api/v1/scenarios?include_archived=true&limit=200')).json()) as {
        items: { scenario_id: string; title_ru: string; archived_at: string | null }[];
      };
      for (const item of list.items.filter((entry) => entry.title_ru === title && entry.archived_at !== null)) {
        const response = await api.post(`/api/v1/scenarios/${item.scenario_id}/unarchive`);
        if (!response.ok()) throw new Error(`разархивация сценария: ${response.status()}`);
      }
    } finally {
      await api.dispose();
    }
  }

  async archiveMaterial(title: string): Promise<void> {
    const api = await this.client(this.env.accounts.instructor);
    try {
      const list = (await (await api.get('/api/v1/materials')).json()) as { items: { material_id: string; title_ru: string }[] };
      for (const item of list.items.filter((entry) => entry.title_ru === title)) {
        const response = await api.post(`/api/v1/materials/${item.material_id}/archive`);
        if (!response.ok()) throw new Error(`архивация материала: ${response.status()}`);
      }
    } finally {
      await api.dispose();
    }
  }
}

export async function runScenario(browser: Browser, scenario: Scenario, env: RunnerEnv): Promise<ScenarioResult> {
  const started = Date.now();
  const shotsDir = path.join(env.resultsDir, 'screenshots');
  const downloadsDir = path.join(env.resultsDir, 'downloads', scenario.id);
  mkdirSync(shotsDir, { recursive: true });
  mkdirSync(downloadsDir, { recursive: true });

  const contexts = new Map<string, BrowserContext>();
  const pages = new Map<string, Page>();
  const credentials = new Map<string, Credentials>(Object.entries(env.accounts));
  const cleanups: { label: string; fn: (api: CleanupApi) => Promise<void> }[] = [];

  const ctx: ScenarioContext = {
    vars: {},
    unique: uniqueSuffix(),
    async page(actor) {
      const existing = pages.get(actor);
      if (existing) return existing;
      const context = await browser.newContext({
        baseURL: env.baseUrl,
        viewport: { width: 1920, height: 1080 },
        locale: 'ru-RU',
        acceptDownloads: true,
        permissions: ['microphone'],
        ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === '1',
      });
      context.setDefaultTimeout(DEFAULT_TIMEOUT_MS);
      context.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT_MS);
      const page = await context.newPage();
      contexts.set(actor, context);
      pages.set(actor, page);
      return page;
    },
    credentials(actor) {
      const found = credentials.get(actor);
      if (!found) throw new Error(`нет логина для «${actor}»`);
      return found;
    },
    setCredentials(actor, value) {
      credentials.set(actor, value);
    },
    onCleanup(label, fn) {
      cleanups.push({ label, fn });
    },
    async download(page, trigger): Promise<Download> {
      const [download] = await Promise.all([page.waitForEvent('download'), trigger()]);
      const fileName = download.suggestedFilename();
      const target = path.join(downloadsDir, fileName);
      await download.saveAs(target);
      return { fileName, path: target, text: () => readFileSync(target, 'utf8') };
    },
    async viewport(actor, size) {
      await (await ctx.page(actor)).setViewportSize(size);
    },
  };

  // I6 HTTP: the http demo has no phone/microphone (§ frontend runtime feature gate on
  // window.isSecureContext) — `E2E_SKIP_SECURE_ONLY=1` skips every `secureOnly` step instead of
  // failing on a now-hidden button, so the rest of the scenario (unaffected by the skip: no
  // secureOnly step sets a `ctx.vars` a later step needs) can still be proven against it.
  const skipSecureOnly = process.env.E2E_SKIP_SECURE_ONLY === '1';

  const result: ScenarioResult = {
    id: scenario.id,
    title: scenario.title,
    status: 'РАБОТАЕТ',
    stepsTotal: scenario.steps.length,
    stepsPassed: 0,
    stepsSkipped: 0,
    durationMs: 0,
    cleanup: [],
  };

  for (const step of scenario.steps) {
    if (step.secureOnly && skipSecureOnly) {
      result.stepsSkipped += 1;
      continue;
    }
    const page = await ctx.page(step.actor);
    const timeout = step.wait?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    page.context().setDefaultTimeout(timeout);
    let notSeen = 'действие шага не удалось выполнить';
    try {
      if (step.action) await step.action(page, ctx);
      for (const expectation of step.expect) {
        notSeen = expectation.see;
        await expectation.run(page, ctx, { expect, timeout });
      }
      result.stepsPassed += 1;
    } catch (error) {
      const shot = path.join(shotsDir, `${step.id}.png`);
      let screenshot: string | null = shot;
      await page.screenshot({ path: shot, fullPage: true }).catch(() => {
        screenshot = null;
      });
      result.status = 'СЛОМАН';
      result.failure = { stepId: step.id, do: step.do, notSeen, error: firstLine(error), screenshot, url: page.url() };
      break;
    } finally {
      page.context().setDefaultTimeout(DEFAULT_TIMEOUT_MS);
    }
  }

  const api = new Api(env);
  for (const cleanup of cleanups.reverse()) {
    try {
      await cleanup.fn(api);
      result.cleanup.push({ label: cleanup.label, ok: true });
    } catch (error) {
      result.cleanup.push({ label: cleanup.label, ok: false, error: firstLine(error) });
    }
  }
  for (const context of contexts.values()) await context.close().catch(() => {});

  result.durationMs = Date.now() - started;
  writeFileSync(path.join(env.resultsDir, `${scenario.id}.json`), JSON.stringify(result, null, 2));
  return result;
}
