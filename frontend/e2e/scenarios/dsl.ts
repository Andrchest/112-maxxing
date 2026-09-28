// I6 SCENARIOS: the small DSL the test scenarios are written in. One source of truth for two
// readers: `doc.ts` renders the definitions as the Russian text a tester (a person, or an AI agent
// that drives a browser by looking at the screen) follows — `docs/test-scenarios/SNN.md`, a table
// «Шаг | Что сделать | Должно быть видно» — and the runner (`runner.ts`) executes every step's
// `action` and `expect` list against a running stand, which keeps that text honest: each «Должно
// быть видно» line IS an assertion's `see`, each «Что сделать» IS the `do` of the action that runs.
//
// This module and the scenario files import only TYPES from `@playwright/test`: the doc renderer
// and its freshness check run under vitest, where Playwright's runtime must not load. Everything
// that needs Playwright's own `expect` receives it from the runner through `Tools`.
import type { Expect, Locator, Page } from '@playwright/test';

/** Who is looking at the screen: a stand account from the env (`admin`, `instructor`,
 * `trainee`) or a temporary account a scenario created itself (any other key). Each actor has its
 * own browser context, as if each role sat at its own PC. */
export type Actor = string;

/** A login and password the runner signs an actor in with. */
export interface Credentials {
  username: string;
  password: string;
}

/** A downloaded file, saved into the run's results dir. */
export interface Download {
  fileName: string;
  path: string;
  text(): string;
}

/** A best-effort cleanup through the backend's REST API (runs even when the scenario broke). */
export interface CleanupApi {
  /** Blocks an account (admin credentials from the env). Missing account — no-op. */
  blockUser(username: string): Promise<void>;
  /** Aborts a lesson with the given owner's credentials. A finished lesson — no-op. */
  abortLesson(lessonId: string, owner: Credentials): Promise<void>;
  /** Unarchives the scenario with this title (instructor credentials from the env). */
  unarchiveScenario(title: string): Promise<void>;
  /** Archives the material with this title (instructor credentials from the env). */
  archiveMaterial(title: string): Promise<void>;
}

export interface ScenarioContext {
  /** The actor's page (opened on first use, 1920×1080 unless `viewport` changed it). */
  page(actor: Actor): Promise<Page>;
  /** Credentials of an actor: the env for the stand accounts, `setCredentials` for temp ones. */
  credentials(actor: Actor): Credentials;
  setCredentials(actor: Actor, credentials: Credentials): void;
  /** Values steps hand to later steps (lesson title and id, a temp user's login, …). */
  vars: Record<string, string>;
  /** Unique per scenario run: every name a scenario creates carries it. */
  unique: string;
  /** Registers a cleanup; all of them run after the scenario, broken or not, in reverse order. */
  onCleanup(label: string, fn: (api: CleanupApi) => Promise<void>): void;
  /** Clicks through `trigger` and returns the file the browser downloaded. */
  download(page: Page, trigger: () => Promise<void>): Promise<Download>;
  /** Resizes the actor's page. */
  viewport(actor: Actor, size: { width: number; height: number }): Promise<void>;
}

/** What an expectation's `run` gets besides the page. */
export interface Tools {
  expect: Expect;
  /** The step's visibility timeout, ms (5 s unless the step declares a legitimate wait). */
  timeout: number;
}

/** One thing that must be visible (or true) after the step's action. */
export interface Expectation {
  /** Russian, for a human: what should be seen. Also the failure message. */
  see: string;
  run(page: Page, ctx: ScenarioContext, tools: Tools): Promise<void>;
}

/** A legitimate product wait: a longer timeout for this step only, and why. */
export interface Wait {
  timeoutMs: number;
  why: string;
}

export interface StepDefinition {
  /** Whose screen the step acts on and checks. */
  actor: Actor;
  /** Russian instruction for a human: what to do. */
  do: string;
  action?: (page: Page, ctx: ScenarioContext) => Promise<void>;
  expect: Expectation[];
  wait?: Wait;
  /** I6 HTTP: the step needs a secure context (the phone/microphone) and does not exist on the
   * temporary http demo. The doc generator marks it «(только https)»; the http bundle and, with
   * `E2E_SKIP_SECURE_ONLY=1`, the runner itself, skip it — the step's id is still reserved by its
   * position (`scenario()` numbers before any filtering), so ids never shift. */
  secureOnly?: boolean;
}

export interface Step extends StepDefinition {
  /** `S03.07`: the scenario id and the step's 1-based position. */
  id: string;
}

export interface ScenarioInfo {
  /** Russian: why this scenario exists. */
  purpose: string;
  /** Russian: what must be true before step 1. */
  preconditions: string[];
  /** Russian: the data the scenario creates or types (names carry the unique suffix). */
  testData: string[];
  /** Russian: what to undo afterwards — always, even when the scenario broke. */
  cleanup: string[];
}

export interface Scenario extends ScenarioInfo {
  id: string;
  title: string;
  /** The actors the scenario uses (for the document). */
  roles: Actor[];
  steps: Step[];
}

/** Declares a scenario; step ids are numbered here, `S03.01`, `S03.02`, … */
export function scenario(
  id: string,
  title: string,
  roles: Actor[],
  steps: StepDefinition[],
  info: ScenarioInfo,
): Scenario {
  return {
    id,
    title,
    roles,
    ...info,
    steps: steps.map((step, index) => ({ ...step, id: `${id}.${String(index + 1).padStart(2, '0')}` })),
  };
}

// -- expectation helpers --------------------------------------------------------------------------

type LocatorFn = (page: Page, ctx: ScenarioContext) => Locator;

/** The element is visible (the first match, when several are). */
export function visible(see: string, locator: LocatorFn): Expectation {
  return {
    see,
    run: async (page, ctx, { expect, timeout }) => {
      await expect(locator(page, ctx).first()).toBeVisible({ timeout });
    },
  };
}

/** No visible element matches. */
export function notVisible(see: string, locator: LocatorFn): Expectation {
  return {
    see,
    run: async (page, ctx, { expect, timeout }) => {
      await expect(locator(page, ctx).filter({ visible: true })).toHaveCount(0, { timeout });
    },
  };
}

/** The text is visible somewhere on the page. */
export function text(see: string, value: string | RegExp): Expectation {
  return visible(see, (page) => page.getByText(value));
}

/** A heading with this name is visible. */
export function heading(name: string, see = `заголовок «${name}»`): Expectation {
  return visible(see, (page) => page.getByRole('heading', { name, exact: true }));
}

/** A button is visible and enabled. */
export function button(name: string, see = `кнопка «${name}», активна`): Expectation {
  return {
    see,
    run: async (page, _ctx, { expect, timeout }) => {
      const target = page.getByRole('button', { name, exact: true }).first();
      await expect(target).toBeVisible({ timeout });
      await expect(target).toBeEnabled({ timeout });
    },
  };
}

/** A button is visible but disabled. */
export function disabledButton(name: string, see = `кнопка «${name}» видна, но неактивна`): Expectation {
  return {
    see,
    run: async (page, _ctx, { expect, timeout }) => {
      const target = page.getByRole('button', { name, exact: true }).first();
      await expect(target).toBeVisible({ timeout });
      await expect(target).toBeDisabled({ timeout });
    },
  };
}

/** A link is visible. */
export function link(name: string, see = `ссылка «${name}»`): Expectation {
  return visible(see, (page) => page.getByRole('link', { name, exact: true }));
}

/** The page address matches. */
export function url(see: string, pattern: RegExp): Expectation {
  return {
    see,
    run: async (page, _ctx, { expect, timeout }) => {
      await expect(page).toHaveURL(pattern, { timeout });
    },
  };
}

/** Any other check; throw (or fail an `expect`) when it does not hold. */
export function check(see: string, run: Expectation['run']): Expectation {
  return { see, run };
}
