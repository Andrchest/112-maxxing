import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionOpenRedirect } from './session-open-redirect';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function makeSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    session: {
      id: 'sess-1', scenario_version_id: 'v1', scenario_slug: 'apartment-fire', scenario_version: 1,
      session_mode: 'FULL_CYCLE_SINGLE_TRAINEE', state: 'ACTIVE', session_seed: 'seed', time_scale: 1,
      incident_id: 'inc-1', role_chain: ['OPERATOR_112', 'DDS'], stages: [], active_role_stage_id: 'stage-1',
      participants: [], created_by_user_id: 'instr-1', created_at: '2026-09-21T00:00:00Z',
      started_at: '2026-09-21T00:00:00Z', completed_at: null, abort_reason: null, monotonic_offset_ms: 1000,
      last_seq_no: 3, transition_pause_seconds: 20, transition_continue_available_at_offset_ms: null,
    },
    my_role_type: null,
    active_role_stage_id: 'stage-1',
    active_role_type: 'OPERATOR_112',
    stage_state: 'INTERVIEW',
    available_actions: [],
    card: { card_id: 'card-1', incident_id: 'inc-1', values: {}, revision_counter: 0, field_specs: [] },
    work_item: null,
    call_state: { call_id: null, room_name: null, phase: 'NO_CALL', caller_display_ru: null, started_at_offset_ms: null, answered_at_offset_ms: null, ended_at_offset_ms: null, duration_ms: null, caller_speaking: false },
    last_seq_no: 3,
    visible_sources: [],
    server_time_utc: '2026-09-21T10:00:00Z',
    ...overrides,
  };
}

function renderAt(sessionId = 'sess-1') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/sessions/${sessionId}/open`]}>
        <Routes>
          <Route path="/sessions/:sessionId/open" element={<SessionOpenRedirect />} />
          <Route path="/operator/:sessionId" element={<div>operator console</div>} />
          <Route path="/dds/:sessionId" element={<div>dds console</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SessionOpenRedirect — resolves the active stage for a FULL_CYCLE_SINGLE_TRAINEE participant (E10)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('redirects to /operator/:id when the active stage is OPERATOR_112', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(makeSnapshot({ active_role_type: 'OPERATOR_112' }))));
    renderAt();
    expect(await screen.findByText('operator console')).toBeInTheDocument();
  });

  it('redirects to /dds/:id when the active stage is DDS', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(makeSnapshot({ active_role_type: 'DDS', card: null }))));
    renderAt();
    expect(await screen.findByText('dds console')).toBeInTheDocument();
  });

  it('shows "no console yet" when there is no active role (e.g. a true observer)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(makeSnapshot({ active_role_type: null, card: null }))));
    renderAt();
    expect(await screen.findByText(ru.sessionsNoConsoleYet)).toBeInTheDocument();
  });
});
