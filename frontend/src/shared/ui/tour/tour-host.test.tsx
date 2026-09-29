// I7 E56: the guided-tour component — steps forward/back, a missing target skipped (or explained),
// a step that opens its own page, a tab activated first, Esc, the focus trap and ←/→.
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/entities/session';
import { TourHost, fitBox, placePopover } from './tour-host';
import { useTourStore } from './tour-store';
import type { TourStep } from './types';

const RECT = { x: 100, y: 100, top: 100, left: 100, right: 300, bottom: 140, width: 200, height: 40, toJSON: () => ({}) };
const NO_RECT = { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}) };

function PageA() {
  return (
    <div>
      <button type="button" data-tour="a-one">
        one
      </button>
      <button type="button" data-tour="a-three">
        three
      </button>
    </div>
  );
}

function PageWithTabs() {
  const [tab, setTab] = useState('first');
  return (
    <div>
      <button type="button" data-tour="tab-second" onMouseDown={() => setTab('second')}>
        second tab
      </button>
      {tab === 'second' ? <div data-tour="second-panel">panel</div> : null}
    </div>
  );
}

function renderTour(initialPath = '/a') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/a" element={<PageA />} />
        <Route path="/b" element={<div data-tour="b-target">b page</div>} />
        <Route path="/tabs" element={<PageWithTabs />} />
      </Routes>
      <TourHost targetWaitMs={150} />
    </MemoryRouter>,
  );
}

function start(steps: TourStep[], fromIndex = 0) {
  act(() => {
    useTourStore.getState().start(steps, fromIndex);
  });
}

async function popover() {
  return screen.findByRole('dialog', { name: /.+/ });
}

describe('TourHost (I7 E56)', () => {
  beforeEach(() => {
    useAuthStore.setState({
      isAuthenticated: true,
      token: 'jwt',
      user: { id: 'u1', username: 'u', display_name_ru: 'U', user_role: 'TRAINEE', created_at: '2026-09-29T00:00:00Z' },
    });
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return (this.hasAttribute('data-tour') ? RECT : NO_RECT) as DOMRect;
    });
  });

  afterEach(() => {
    act(() => useTourStore.getState().stop());
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false });
    vi.restoreAllMocks();
  });

  const THREE: TourStep[] = [
    { id: 's1', route: '/a', target: 'a-one', title: 'Шаг один', text: 'Текст один' },
    { id: 's2', route: '/a', target: 'a-two', title: 'Шаг два', text: 'Текст два' },
    { id: 's3', route: '/a', target: 'a-three', title: 'Шаг три', text: 'Текст три' },
  ];

  it('shows the step title, text and «1 из 3», and walks «Далее» / «Назад»', async () => {
    renderTour();
    start([THREE[0]!, { ...THREE[1]!, target: 'a-three' }, THREE[2]!]);
    expect(await popover()).toHaveAccessibleName('Шаг один');
    expect(screen.getByText('Текст один')).toBeInTheDocument();
    expect(screen.getByText('1 из 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
    expect(document.querySelector('[data-slot="tour-spotlight"]')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Далее' }));
    expect(await screen.findByRole('dialog', { name: 'Шаг два' })).toBeInTheDocument();
    expect(screen.getByText('2 из 3')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('dialog', { name: 'Шаг один' })).toBeInTheDocument();
  });

  it('skips a step whose target is missing (no crash, no empty spotlight)', async () => {
    renderTour();
    start(THREE);
    await popover();
    await userEvent.click(screen.getByRole('button', { name: 'Далее' }));
    expect(await screen.findByRole('dialog', { name: 'Шаг три' }, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByText('3 из 3')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Шаг два' })).not.toBeInTheDocument();
    // Going back from 3 skips the missing step 2 the other way.
    await userEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('dialog', { name: 'Шаг один' }, { timeout: 2000 })).toBeInTheDocument();
  });

  it('shows a missing-target step as centred text when it asks to explain instead', async () => {
    renderTour();
    start([{ ...THREE[1]!, explainIfMissing: true }]);
    expect(await screen.findByRole('dialog', { name: 'Шаг два' }, { timeout: 2000 })).toBeInTheDocument();
    expect(document.querySelector('[data-slot="tour-spotlight"]')).not.toBeInTheDocument();
  });

  it('ends the tour when the last step is missing, and «Готово» ends it on the last one', async () => {
    renderTour();
    start([THREE[0]!, THREE[1]!]);
    await popover();
    await userEvent.click(screen.getByRole('button', { name: 'Далее' }));
    await vi.waitFor(() => expect(useTourStore.getState().active).toBe(false), { timeout: 2000 });

    start([THREE[0]!]);
    await popover();
    await userEvent.click(screen.getByRole('button', { name: 'Готово' }));
    expect(useTourStore.getState().active).toBe(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens the step’s own page first (a tour spans pages)', async () => {
    renderTour('/a');
    start([{ id: 'b', route: '/b', target: 'b-target', title: 'Страница Б', text: 'Текст' }]);
    expect(await screen.findByRole('dialog', { name: 'Страница Б' })).toBeInTheDocument();
    expect(screen.getByText('b page')).toBeInTheDocument();
  });

  it('clicks `activate` (a tab) before looking for the target', async () => {
    renderTour('/tabs');
    start([{ id: 't', route: '/tabs', activate: 'tab-second', target: 'second-panel', title: 'Вкладка', text: 'Текст' }]);
    expect(await screen.findByRole('dialog', { name: 'Вкладка' })).toBeInTheDocument();
    expect(screen.getByText('panel')).toBeInTheDocument();
  });

  it('Esc and «Пропустить» close the tour', async () => {
    renderTour();
    start(THREE);
    await popover();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(useTourStore.getState().active).toBe(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    start(THREE);
    await popover();
    await userEvent.click(screen.getByRole('button', { name: 'Пропустить' }));
    expect(useTourStore.getState().active).toBe(false);
  });

  it('is keyboard accessible: «Далее» focused, Tab stays inside the popover, → / ← step', async () => {
    renderTour();
    start([THREE[0]!, { ...THREE[2]!, id: 's3' }]);
    await popover();
    const next = screen.getByRole('button', { name: 'Далее' });
    await vi.waitFor(() => expect(next).toHaveFocus());

    // «Назад» is disabled on step 1: the trap cycles between «Пропустить» and «Далее».
    await userEvent.tab();
    expect(screen.getByRole('button', { name: 'Пропустить' })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(next).toHaveFocus();

    fireEvent.keyDown(next, { key: 'ArrowRight' });
    expect(await screen.findByRole('dialog', { name: 'Шаг три' })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Готово' }), { key: 'ArrowLeft' });
    expect(await screen.findByRole('dialog', { name: 'Шаг один' })).toBeInTheDocument();
  });

  it('stops the tour on sign-out', async () => {
    renderTour();
    start(THREE);
    await popover();
    act(() => useAuthStore.setState({ token: null, user: null, isAuthenticated: false }));
    expect(useTourStore.getState().active).toBe(false);
  });
});

describe('placePopover (I7 E56)', () => {
  const viewport = { width: 1280, height: 800 };
  const size = { width: 380, height: 180 };

  it('goes below the target when there is room, centred on it and inside the viewport', () => {
    expect(placePopover({ top: 50, left: 0, width: 100, height: 40 }, size, viewport)).toEqual({ top: 102, left: 16 });
  });

  it('goes above when there is no room below', () => {
    expect(placePopover({ top: 700, left: 400, width: 200, height: 60 }, size, viewport)).toEqual({ top: 508, left: 310 });
  });

  it('goes beside a tall target, and to the bottom-right corner when nothing fits', () => {
    expect(placePopover({ top: 20, left: 20, width: 500, height: 760 }, size, viewport)).toEqual({ top: 310, left: 532 });
    expect(placePopover({ top: 0, left: 0, width: 1280, height: 800 }, size, viewport)).toEqual({ top: 604, left: 884 });
  });

  it('highlights only the top of a target too tall for the popover to fit anywhere around it', () => {
    const tall = { top: 60, left: 0, width: 1280, height: 1500 };
    const fitted = fitBox(tall, size, viewport);
    expect(fitted).toEqual({ top: 60, left: 0, width: 1280, height: 532 });
    expect(placePopover(fitted, size, viewport)).toEqual({ top: 604, left: 450 });
    // A target with room below keeps its whole box.
    expect(fitBox({ top: 50, left: 0, width: 100, height: 40 }, size, viewport)).toEqual({ top: 50, left: 0, width: 100, height: 40 });
  });

  it('centres a text-only step', () => {
    expect(placePopover(null, size, viewport)).toEqual({ top: 310, left: 450 });
  });
});
