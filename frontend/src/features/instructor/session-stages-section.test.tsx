import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SessionStagesSection } from './session-stages-section';
import { ru } from '@/shared/i18n/ru';
import { makeRoleStageView, makeSessionDetail } from './test-fixtures';

describe('SessionStagesSection — session state, active role, stages, transition countdown', () => {
  it('renders the session state and the active role', () => {
    const session = makeSessionDetail({ state: 'ACTIVE', active_role_stage_id: 'stage-1' });
    render(<SessionStagesSection session={session} stages={[makeRoleStageView({ role_stage_id: 'stage-1', role_type: 'OPERATOR_112' })]} />);
    expect(screen.getByText(new RegExp(`${ru.sessionsStateLabel}: ${ru.sessionStateActive}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`${ru.instructorOverviewActiveRoleLabel}: ${ru.roleTypeOperator112}`))).toBeInTheDocument();
  });

  it('renders "no active role" when nothing matches active_role_stage_id', () => {
    const session = makeSessionDetail({ active_role_stage_id: null });
    render(<SessionStagesSection session={session} stages={[makeRoleStageView()]} />);
    expect(screen.getByText(new RegExp(ru.instructorOverviewNoActiveRole))).toBeInTheDocument();
  });

  it('renders the countdown only while ROLE_TRANSITION, from server-sent offsets', () => {
    const session = makeSessionDetail({
      state: 'ROLE_TRANSITION',
      monotonic_offset_ms: 5000,
      transition_continue_available_at_offset_ms: 25000,
    });
    render(<SessionStagesSection session={session} stages={[makeRoleStageView()]} />);
    expect(screen.getByText(new RegExp(`${ru.operatorRoleTransitionCountdownLabel}: 20`))).toBeInTheDocument();
  });

  it('renders "ready" once the pause has elapsed', () => {
    const session = makeSessionDetail({
      state: 'ROLE_TRANSITION',
      monotonic_offset_ms: 30000,
      transition_continue_available_at_offset_ms: 25000,
    });
    render(<SessionStagesSection session={session} stages={[makeRoleStageView()]} />);
    expect(screen.getByText(ru.operatorRoleTransitionReady)).toBeInTheDocument();
  });

  it('shows each stage with its participant and role', () => {
    const stages = [
      makeRoleStageView({ role_stage_id: 'stage-1', role_type: 'OPERATOR_112', participant_user_id: 'trainee-1' }),
      makeRoleStageView({ role_stage_id: 'stage-2', role_type: 'DDS', participant_user_id: null }),
    ];
    render(<SessionStagesSection session={makeSessionDetail({ active_role_stage_id: 'stage-1' })} stages={stages} />);
    expect(screen.getByText(new RegExp(`${ru.instructorOverviewStageParticipantLabel}: trainee-1`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ru.instructorOverviewStageNoParticipant))).toBeInTheDocument();
  });
});
