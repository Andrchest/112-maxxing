import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ResourceTimelineSection } from './resource-timeline-section';
import { ru } from '@/shared/i18n/ru';
import { makeResourceTimelineEntry } from './test-fixtures';

describe('ResourceTimelineSection — renders resource_timeline verbatim', () => {
  it('renders the empty state when there are no entries', () => {
    render(<ResourceTimelineSection entries={[]} />);
    expect(screen.getByText(ru.reportResourceTimelineEmpty)).toBeInTheDocument();
  });

  it('renders the callsign and previous/new status for each step', () => {
    render(<ResourceTimelineSection entries={[makeResourceTimelineEntry({ callsign: 'UNIT-1', previous_status: 'SELECTED', new_status: 'DISPATCHED' })]} />);
    expect(screen.getByText('UNIT-1')).toBeInTheDocument();
    expect(screen.getByText(ru.resourceStatusSelected)).toBeInTheDocument();
    expect(screen.getByText(ru.resourceStatusDispatched)).toBeInTheDocument();
  });

  it('renders factValueEmpty for a unit\'s first recorded transition (null previous_status)', () => {
    render(<ResourceTimelineSection entries={[makeResourceTimelineEntry({ callsign: 'UNIT-2', previous_status: null, new_status: 'AVAILABLE' })]} />);
    expect(screen.getByText('UNIT-2')).toBeInTheDocument();
    expect(screen.getByText(ru.factValueEmpty)).toBeInTheDocument();
    expect(screen.getByText(ru.resourceStatusAvailable)).toBeInTheDocument();
  });
});
