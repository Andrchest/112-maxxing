import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { InferenceHealthSection } from './inference-health-section';
import { ru } from '@/shared/i18n/ru';
import { makeHealthReadyResponse } from './test-fixtures';

describe('InferenceHealthSection — HealthReadyResponse', () => {
  it('renders the overall readiness and required components', () => {
    render(<InferenceHealthSection health={makeHealthReadyResponse({ overall: 'READY', required_components: ['asr', 'llm'] })} />);
    expect(screen.getByText(ru.readinessReady)).toBeInTheDocument();
    expect(screen.getByText(new RegExp('asr, llm'))).toBeInTheDocument();
  });

  it('renders per-component status when present', () => {
    render(
      <InferenceHealthSection
        health={makeHealthReadyResponse({
          components: [{ component: 'llm', status: 'FATAL', detail: 'timeout', checked_at: '2026-09-21T00:00:00Z' }],
        })}
      />,
    );
    expect(screen.getByText(new RegExp(`^llm: ${ru.readinessFatal}$`))).toBeInTheDocument();
  });
});
