import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { RuleEvidenceSection } from './rule-evidence-section';
import { ru } from '@/shared/i18n/ru';
import { makeScoreEvidence, makeScoreResult } from './test-fixtures';

describe('RuleEvidenceSection — every rule row expands to its evidence list (§29 item 14)', () => {
  it('renders the empty state when there are no results', () => {
    render(<RuleEvidenceSection results={[]} />);
    expect(screen.getByText(ru.reportEvidenceEmpty)).toBeInTheDocument();
  });

  it('does not show evidence until the row is expanded', () => {
    render(<RuleEvidenceSection results={[makeScoreResult({ evidence: [makeScoreEvidence({ note_ru: 'evidence note' })] })]} />);
    expect(screen.queryByText('evidence note')).not.toBeInTheDocument();
  });

  it('shows the evidence list after clicking expand', async () => {
    const user = userEvent.setup();
    render(<RuleEvidenceSection results={[makeScoreResult({ evidence: [makeScoreEvidence({ note_ru: 'evidence note' })] })]} />);

    await user.click(screen.getByRole('button', { name: ru.reportEvidenceExpandButton }));

    expect(screen.getByText('evidence note')).toBeInTheDocument();
  });

  it('calls onJumpToEvent with the evidence seq_no when the jump button is clicked', async () => {
    const user = userEvent.setup();
    const onJumpToEvent = vi.fn();
    render(
      <RuleEvidenceSection
        results={[makeScoreResult({ evidence: [makeScoreEvidence({ note_ru: 'evidence note', seq_no: 7 })] })]}
        onJumpToEvent={onJumpToEvent}
      />,
    );

    await user.click(screen.getByRole('button', { name: ru.reportEvidenceExpandButton }));
    await user.click(screen.getByRole('button', { name: ru.reportEvidenceJumpToEventButton }));

    expect(onJumpToEvent).toHaveBeenCalledWith(7);
  });

  it('renders no jump button for an evidence item with no seq_no', async () => {
    const user = userEvent.setup();
    render(<RuleEvidenceSection results={[makeScoreResult({ evidence: [makeScoreEvidence({ note_ru: 'evidence note', seq_no: null })] })]} onJumpToEvent={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: ru.reportEvidenceExpandButton }));

    expect(screen.queryByRole('button', { name: ru.reportEvidenceJumpToEventButton })).not.toBeInTheDocument();
  });
});
