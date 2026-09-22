import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CallStateSection } from './call-state-section';
import { ru } from '@/shared/i18n/ru';
import { makeCallStateView } from './test-fixtures';

describe('CallStateSection — the phone widget state, read-only', () => {
  it('renders the phase label', () => {
    render(<CallStateSection callState={makeCallStateView({ phase: 'RINGING' })} />);
    expect(screen.getByText(ru.callPhaseRinging)).toBeInTheDocument();
  });

  it('renders duration when the call has one', () => {
    render(<CallStateSection callState={makeCallStateView({ duration_ms: 12000 })} />);
    expect(screen.getByText(new RegExp(`${ru.instructorCallStateDurationLabel}: 12000`))).toBeInTheDocument();
  });

  it('renders no duration line when null', () => {
    render(<CallStateSection callState={makeCallStateView({ duration_ms: null })} />);
    expect(screen.queryByText(new RegExp(ru.instructorCallStateDurationLabel))).not.toBeInTheDocument();
  });
});
