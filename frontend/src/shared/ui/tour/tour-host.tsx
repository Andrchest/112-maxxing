// I7 E56: the guided-tour overlay (no npm dependency). Mounted once inside the router (`app/App.tsx`)
// so a tour survives the page changes it makes. For the current step it: opens the step's `route`
// if the browser is elsewhere; clicks `activate` (a tab) if given; waits a little for
// `[data-tour="<target>"]` to appear (the page may still be loading); scrolls it into view; dims the
// page around it and shows a popover with the text, «3 из 9», «Назад» / «Далее» / «Пропустить».
// A step whose target never shows up is skipped (or, with `explainIfMissing`, shown as centred
// text) — never a crash and never an empty spotlight. Esc closes; focus stays inside the popover;
// ← / → step back and forth. The popover re-positions on resize and scroll.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router';
import { cn } from 'cn';
import { Button } from '@/shared/ui/button';
import { t } from '@/shared/i18n';
import { useAuthStore } from '@/entities/session';
import { stepPageMatches, useTourStore } from './tour-store';

/** How long a step waits for its target to render before it is skipped (or explained). */
export const TARGET_WAIT_MS = 3000;
const POLL_MS = 100;
/** Gap between the highlighted element and the popover, viewport margin, spotlight padding. */
const GAP = 12;
const MARGIN = 16;
const PAD = 6;
const POPOVER_MAX_WIDTH = 380;

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** The first `[data-tour="<id>"]` that is actually rendered (non-zero box). */
export function findTourTarget(id: string): HTMLElement | null {
  for (const node of document.querySelectorAll<HTMLElement>(`[data-tour="${id}"]`)) {
    const rect = node.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return node;
  }
  return null;
}

/** A click the way a mouse makes one — Radix tabs switch on `mousedown`, links/buttons on `click`. */
function activateElement(element: HTMLElement): void {
  element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
  element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, button: 0 }));
  element.click();
}

/** Keeps the 3 px ring visible for an element flush with a viewport edge (a pinned bottom bar). */
const EDGE = 3;

/** The part of `rect` inside the viewport, padded for the spotlight ring. */
function spotlightBox(rect: DOMRect, viewport: { width: number; height: number }): Box {
  const top = Math.max(rect.top - PAD, EDGE);
  const left = Math.max(rect.left - PAD, EDGE);
  const bottom = Math.min(rect.bottom + PAD, viewport.height - EDGE);
  const right = Math.min(rect.right + PAD, viewport.width - EDGE);
  return { top, left, width: Math.max(right - left, 0), height: Math.max(bottom - top, 0) };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

/**
 * Where the popover goes: below the highlighted box, else above, right, left; when none fits (a
 * box taller and wider than the room around it) — the viewport's bottom-right corner. With no box,
 * centred. Always kept inside the viewport with a 16 px margin.
 */
export function placePopover(
  box: Box | null,
  popover: { width: number; height: number },
  viewport: { width: number; height: number },
): { top: number; left: number } {
  const { width, height } = popover;
  const maxLeft = viewport.width - width - MARGIN;
  const maxTop = viewport.height - height - MARGIN;
  if (!box) return { top: clamp((viewport.height - height) / 2, MARGIN, maxTop), left: clamp((viewport.width - width) / 2, MARGIN, maxLeft) };
  const centredLeft = clamp(box.left + box.width / 2 - width / 2, MARGIN, maxLeft);
  const centredTop = clamp(box.top + box.height / 2 - height / 2, MARGIN, maxTop);
  const bottom = box.top + box.height;
  const right = box.left + box.width;
  if (bottom + GAP + height <= viewport.height - MARGIN) return { top: bottom + GAP, left: centredLeft };
  if (box.top - GAP - height >= MARGIN) return { top: box.top - GAP - height, left: centredLeft };
  if (right + GAP + width <= viewport.width - MARGIN) return { top: centredTop, left: right + GAP };
  if (box.left - GAP - width >= MARGIN) return { top: centredTop, left: box.left - GAP - width };
  return { top: Math.max(maxTop, MARGIN), left: Math.max(maxLeft, MARGIN) };
}

/**
 * A target taller than the room around the popover (a long list, a whole form) is highlighted by
 * its top part only, so the popover can sit below it instead of covering it: the box is cut to the
 * height that leaves room for the popover underneath. Boxes with room beside or above are kept.
 */
export function fitBox(box: Box, popover: { width: number; height: number }, viewport: { width: number; height: number }): Box {
  const bottom = box.top + box.height;
  const fitsBelow = bottom + GAP + popover.height <= viewport.height - MARGIN;
  const fitsAbove = box.top - GAP - popover.height >= MARGIN;
  const fitsBeside =
    box.left + box.width + GAP + popover.width <= viewport.width - MARGIN || box.left - GAP - popover.width >= MARGIN;
  if (fitsBelow || fitsAbove || fitsBeside) return box;
  const height = viewport.height - MARGIN - popover.height - GAP - box.top;
  return height >= 40 ? { ...box, height } : box;
}

function viewportSize(): { width: number; height: number } {
  return { width: window.innerWidth, height: window.innerHeight };
}

function sameBox(a: Box | null, b: Box | null): boolean {
  if (a === null || b === null) return a === b;
  return a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height;
}

interface Shown {
  /** `<step index>|<pathname>` the resolution was made for; stale once either changes. */
  key: string;
  target: HTMLElement | null;
}

function TourRunner({ targetWaitMs }: { targetWaitMs: number }) {
  const steps = useTourStore((state) => state.steps);
  const index = useTourStore((state) => state.index);
  const next = useTourStore((state) => state.next);
  const back = useTourStore((state) => state.back);
  const skip = useTourStore((state) => state.skip);
  const stop = useTourStore((state) => state.stop);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const step = steps[index];
  const key = `${index}|${pathname}`;
  const [shown, setShown] = useState<Shown | null>(null);
  /** The step index this runner already navigated for — a route that redirects elsewhere (a
   * guard) is then treated as a missing target instead of navigating in a loop. */
  const navigatedFor = useRef<number | null>(null);

  // Resolve the current step: navigate, activate, wait for the target, or skip. Every state update
  // happens in a timer callback, never synchronously in the effect body.
  useEffect(() => {
    if (!step) return undefined;
    let cancelled = false;
    let timer: number | undefined;
    const startedAt = Date.now();
    let activated = step.activate === undefined;

    const missing = () => {
      if (step.explainIfMissing) setShown({ key, target: null });
      else skip();
    };

    const poll = () => {
      if (cancelled) return;
      if (step.route && pathname !== step.route) {
        if (navigatedFor.current !== index) {
          navigatedFor.current = index;
          navigate(step.route);
          return;
        }
        missing();
        return;
      }
      navigatedFor.current = null;
      if (!step.target) {
        setShown({ key, target: null });
        return;
      }
      if (!stepPageMatches(step, pathname)) {
        missing();
        return;
      }
      if (!activated && step.activate) {
        const activator = findTourTarget(step.activate);
        if (activator) {
          activateElement(activator);
          activated = true;
        }
      }
      const target = activated ? findTourTarget(step.target) : null;
      if (target) {
        // A tall target (a long list) shows its top; anything else is centred.
        const tall = target.getBoundingClientRect().height > window.innerHeight * 0.6;
        target.scrollIntoView?.({ block: tall ? 'start' : 'center', inline: 'nearest' });
        setShown({ key, target });
        return;
      }
      if (Date.now() - startedAt >= targetWaitMs) {
        missing();
        return;
      }
      timer = window.setTimeout(poll, POLL_MS);
    };

    timer = window.setTimeout(poll, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [key, step, index, pathname, navigate, skip, targetWaitMs]);

  if (!step || !shown || shown.key !== key) return null;
  return (
    <TourPopover
      key={key}
      stepIndex={index}
      total={steps.length}
      title={step.title}
      text={step.text}
      target={shown.target}
      isLast={index === steps.length - 1}
      onBack={back}
      onNext={() => {
        if (step.clickOnNext && shown.target) shown.target.click();
        next();
      }}
      onClose={stop}
    />
  );
}

interface TourPopoverProps {
  stepIndex: number;
  total: number;
  title: string;
  text: string;
  target: HTMLElement | null;
  isLast: boolean;
  onBack: () => void;
  onNext: () => void;
  onClose: () => void;
}

function TourPopover({ stepIndex, total, title, text, target, isLast, onBack, onNext, onClose }: TourPopoverProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const [box, setBox] = useState<Box | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  const measure = useCallback(() => {
    const viewport = viewportSize();
    const nextBox = target && target.isConnected ? spotlightBox(target.getBoundingClientRect(), viewport) : null;
    const dialog = dialogRef.current;
    const size = dialog ? { width: dialog.offsetWidth, height: dialog.offsetHeight } : { width: 0, height: 0 };
    const visibleBox = nextBox && nextBox.width > 0 && nextBox.height > 0 ? fitBox(nextBox, size, viewport) : null;
    setBox((current) => (sameBox(current, visibleBox) ? current : visibleBox));
    const nextPosition = placePopover(visibleBox, size, viewport);
    setPosition((current) => (current && current.top === nextPosition.top && current.left === nextPosition.left ? current : nextPosition));
  }, [target]);

  // Position on the next frame (the popover is laid out, hidden, first), then re-position on resize
  // and on any scroll (the consoles scroll an inner region, hence capture), plus a slow poll for
  // layout shifts (data arriving under a loading page).
  useEffect(() => {
    let frame = 0;
    const schedule = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measure);
    };
    schedule();
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    const interval = window.setInterval(measure, 300);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', schedule);
      window.removeEventListener('scroll', schedule, true);
      window.clearInterval(interval);
    };
  }, [measure]);

  useEffect(() => {
    nextRef.current?.focus();
  }, []);

  // Esc closes from anywhere; Tab never leaves the popover (focus trap).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>('button:not([disabled])'));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      if (!dialog.contains(active)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown, true);
    return () => document.removeEventListener('keydown', onKeyDown, true);
  }, [onClose]);

  function onDialogKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      onNext();
    } else if (event.key === 'ArrowLeft' && stepIndex > 0) {
      event.preventDefault();
      onBack();
    }
  }

  // The organizer's light reference screens (`.reference-light`) keep their look in the popover too.
  const lightTheme = Boolean((target ?? document.querySelector('main'))?.closest('.reference-light'));
  const counter = t('tourStepCounter').replace('{current}', String(stepIndex + 1)).replace('{total}', String(total));
  const titleId = `tour-title-${stepIndex}`;
  const textId = `tour-text-${stepIndex}`;

  return createPortal(
    <div className="fixed inset-0 z-[1000]" data-slot="tour-overlay">
      {box ? (
        <div
          aria-hidden="true"
          data-slot="tour-spotlight"
          className="pointer-events-none fixed rounded-lg outline-3 outline-amber-400 transition-all duration-150"
          style={{ top: box.top, left: box.left, width: box.width, height: box.height, boxShadow: '0 0 0 9999px rgb(0 0 0 / 0.6)' }}
        />
      ) : (
        <div aria-hidden="true" className="fixed inset-0 bg-black/60" />
      )}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={textId}
        data-slot="tour-popover"
        data-tour-step={stepIndex + 1}
        onKeyDown={onDialogKeyDown}
        className={cn(
          'fixed flex flex-col gap-3 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-2xl',
          lightTheme ? 'reference-light' : '',
        )}
        style={{
          width: `min(${POPOVER_MAX_WIDTH}px, calc(100vw - ${2 * MARGIN}px))`,
          top: position?.top ?? MARGIN,
          left: position?.left ?? MARGIN,
          visibility: position ? 'visible' : 'hidden',
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold leading-snug">
            {title}
          </h2>
          <span className="shrink-0 pt-0.5 text-xs text-muted-foreground tabular-nums" data-slot="tour-counter">
            {counter}
          </span>
        </div>
        <p id={textId} className="text-sm leading-relaxed">
          {text}
        </p>
        <div className="flex items-center justify-between gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            {t('tourSkipButton')}
          </Button>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={onBack} disabled={stepIndex === 0}>
              {t('tourBackButton')}
            </Button>
            <Button ref={nextRef} type="button" size="sm" onClick={onNext}>
              {isLast ? t('tourDoneButton') : t('tourNextButton')}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * The app-level tour host: renders the running tour (if any) and stops it on sign-out. Must sit
 * inside the router. `targetWaitMs` is shortened by tests only.
 */
export function TourHost({ targetWaitMs = TARGET_WAIT_MS }: { targetWaitMs?: number }) {
  const active = useTourStore((state) => state.active);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const stop = useTourStore((state) => state.stop);

  useEffect(() => {
    if (!isAuthenticated && active) stop();
  }, [isAuthenticated, active, stop]);

  // Focus goes back where it was (the «Обучение» button, the card) when the tour ends.
  const returnFocusTo = useRef<Element | null>(null);
  useEffect(() => {
    if (active) {
      returnFocusTo.current = document.activeElement;
      return undefined;
    }
    const element = returnFocusTo.current;
    returnFocusTo.current = null;
    if (element instanceof HTMLElement && element.isConnected) element.focus();
    return undefined;
  }, [active]);

  if (!active || !isAuthenticated) return null;
  return <TourRunner targetWaitMs={targetWaitMs} />;
}
