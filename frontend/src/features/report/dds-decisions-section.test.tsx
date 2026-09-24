import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DdsDecisionsSection } from './dds-decisions-section';
import { ru } from '@/shared/i18n/ru';
import { makeDdsDecision } from './test-fixtures';

describe('DdsDecisionsSection — renders dds_decisions verbatim', () => {
  it('renders the empty state when there are no decisions', () => {
    render(<DdsDecisionsSection decisions={[]} />);
    expect(screen.getByText(ru.reportDdsDecisionsEmpty)).toBeInTheDocument();
  });

  it('renders the service badge, dispatch callsigns and closure reason', () => {
    render(
      <DdsDecisionsSection
        decisions={[
          makeDdsDecision({
            service_type: 'FIRE_RESCUE',
            dispatch_events: [{ at_offset_ms: 3000, resource_ids: ['r1'], callsigns: ['UNIT-1'], is_additional: false }],
            closure_reason: 'RESOLVED',
          }),
        ]}
      />,
    );
    expect(screen.getByText(ru.serviceTypeFireRescue)).toBeInTheDocument();
    expect(screen.getByText('UNIT-1')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ru.closureReasonResolved))).toBeInTheDocument();
  });

  // I3 E5c: the memo's leg status + responder + history + card issues (70 §70.4, D16).
  it('renders the response status, responder and the status history/card issues', () => {
    render(
      <DdsDecisionsSection
        decisions={[
          makeDdsDecision({
            response_status: 'ACCEPTED',
            responder: 'SCRIPTED',
            status_history: [
              {
                event_id: 'e1',
                previous_status: 'RECEIVED',
                new_status: 'ACCEPTED',
                order_number: '23',
                comment_ru: null,
                completion_reason: null,
                source: 'SCRIPTED_RESPONDER',
                actor_user_id: null,
                actor_display_ru: 'Fire service',
                at_offset_ms: 15000,
              },
            ],
            card_issues: [
              { event_id: 'issue-1', assignment_id: 'assignment-1', field_path: 'address.house', issue_kind: 'WRONG', comment_ru: 'Wrong house number', at_offset_ms: 5000 },
            ],
          }),
        ]}
      />,
    );
    expect(screen.getAllByText(new RegExp(ru.serviceResponseStatusAccepted)).length).toBeGreaterThan(0);
    expect(screen.getByText(new RegExp(ru.reportDdsResponderScripted))).toBeInTheDocument();
    expect(screen.getAllByText('Fire service').length).toBeGreaterThan(0);
    expect(screen.getByText(/23/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ru.cardIssueKindWrong))).toBeInTheDocument();
    expect(screen.getByText(/Wrong house number/)).toBeInTheDocument();
  });

  it('renders status updates with their kind label and text_ru', () => {
    render(
      <DdsDecisionsSection
        decisions={[
          makeDdsDecision({
            status_updates: [{ assignment_id: 'assignment-1', update_kind: 'ON_SCENE_REPORT', text_ru: 'on scene', at_offset_ms: 4000, actor_user_id: 'u1' }],
          }),
        ]}
      />,
    );
    expect(screen.getByText(new RegExp(ru.statusUpdateKindOnSceneReport))).toBeInTheDocument();
    expect(screen.getByText(/on scene/)).toBeInTheDocument();
  });
});
