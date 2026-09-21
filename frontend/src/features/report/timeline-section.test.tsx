import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { TimelineSection } from './timeline-section';
import { ru } from '@/shared/i18n/ru';
import { makeTimelineEntry } from './test-fixtures';

// `summary_ru` is server-generated free text; every fixture override below uses a non-Cyrillic
// placeholder only so the literal never trips `no-cyrillic-guard.test.ts` (which scans every
// .tsx source file) — the component renders whatever the API returns verbatim, in Russian in
// production.
describe('TimelineSection — renders summary_ru verbatim, filters by actor/event type', () => {
  it('renders the empty state for an empty timeline', () => {
    render(<TimelineSection timeline={[]} />);
    expect(screen.getByText(ru.reportTimelineEmpty)).toBeInTheDocument();
  });

  it('renders one row per entry with its summary_ru', () => {
    render(
      <TimelineSection
        timeline={[
          makeTimelineEntry({ seq_no: 1, summary_ru: 'call answered', actor_type: 'TRAINEE' }),
          makeTimelineEntry({ seq_no: 2, summary_ru: 'card handed off', actor_type: 'SIMULATION' }),
        ]}
      />,
    );
    expect(screen.getByText('call answered')).toBeInTheDocument();
    expect(screen.getByText('card handed off')).toBeInTheDocument();
  });

  it('filters rows by the selected actor', async () => {
    const user = userEvent.setup();
    render(
      <TimelineSection
        timeline={[
          makeTimelineEntry({ seq_no: 1, summary_ru: 'call answered', actor_type: 'TRAINEE' }),
          makeTimelineEntry({ seq_no: 2, summary_ru: 'card handed off', actor_type: 'SIMULATION' }),
        ]}
      />,
    );

    await user.selectOptions(screen.getByLabelText(ru.reportTimelineActorFilterLabel), ru.actorTypeTrainee);

    expect(screen.getByText('call answered')).toBeInTheDocument();
    expect(screen.queryByText('card handed off')).not.toBeInTheDocument();
  });

  it('highlights the row matching highlightedSeqNo', () => {
    render(<TimelineSection timeline={[makeTimelineEntry({ seq_no: 5, summary_ru: 'resource dispatched' })]} highlightedSeqNo={5} />);
    expect(screen.getByText('resource dispatched').closest('li')).toHaveClass('ring-primary');
  });
});
