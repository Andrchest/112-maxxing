// I7 E56: the running tour's state — a module-level zustand store, so the overlay (mounted once at
// the app root, `TourHost`) survives the page changes a tour makes, and any header button can
// (re)start it.
import { create } from 'zustand';
import type { TourStep } from './types';

interface TourState {
  steps: readonly TourStep[];
  index: number;
  /** +1 after «Далее», −1 after «Назад»: which way a skipped step (missing target) moves. */
  direction: 1 | -1;
  active: boolean;
  start: (steps: readonly TourStep[], fromIndex?: number) => void;
  next: () => void;
  back: () => void;
  /** Moves on past a step whose target is missing, in the current direction. */
  skip: () => void;
  stop: () => void;
}

export const useTourStore = create<TourState>((set, get) => ({
  steps: [],
  index: 0,
  direction: 1,
  active: false,
  start: (steps, fromIndex = 0) => {
    if (steps.length === 0) return;
    set({ steps, index: Math.min(Math.max(fromIndex, 0), steps.length - 1), direction: 1, active: true });
  },
  next: () => {
    const { index, steps } = get();
    if (index + 1 >= steps.length) set({ active: false });
    else set({ index: index + 1, direction: 1 });
  },
  back: () => {
    const { index } = get();
    if (index > 0) set({ index: index - 1, direction: -1 });
  },
  skip: () => {
    const { index, steps, direction } = get();
    const target = index + direction;
    if (target >= steps.length) {
      set({ active: false });
    } else if (target < 0) {
      // Walking back past the first step: turn round, so a «Назад» never ends the tour.
      if (index + 1 < steps.length) set({ index: index + 1, direction: 1 });
      else set({ active: false });
    } else {
      set({ index: target });
    }
  },
  stop: () => set({ active: false }),
}));

/** Whether `pathname` is the page the step's target lives on. */
export function stepPageMatches(step: TourStep, pathname: string): boolean {
  if (step.page) return step.page.test(pathname);
  if (step.route) return step.route === pathname;
  return true;
}

/** The first step that belongs to the page `pathname` (the header button starts the tour from
 * the current page), or -1 when this page has no segment of its own. */
export function segmentIndexForPath(steps: readonly TourStep[], pathname: string): number {
  return steps.findIndex((step) => (step.route !== undefined || step.page !== undefined) && stepPageMatches(step, pathname));
}
