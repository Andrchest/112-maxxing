import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { AppRoutes } from '@/app/router';
import { ru } from '@/shared/i18n/ru';

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe('AppRoutes', () => {
  it('renders the operator placeholder with its Russian title', () => {
    renderAt('/operator');
    expect(screen.getByRole('heading', { name: ru.operatorTitle })).toBeInTheDocument();
  });

  it('renders the dds placeholder with its Russian title', () => {
    renderAt('/dds');
    expect(screen.getByRole('heading', { name: ru.ddsTitle })).toBeInTheDocument();
  });

  it('renders the instructor placeholder with its Russian title', () => {
    renderAt('/instructor');
    expect(screen.getByRole('heading', { name: ru.instructorTitle })).toBeInTheDocument();
  });

  it('renders the report placeholder with its Russian title', () => {
    renderAt('/report');
    expect(screen.getByRole('heading', { name: ru.reportTitle })).toBeInTheDocument();
  });

  it('redirects / to /login', () => {
    renderAt('/');
    expect(screen.getByRole('heading', { name: ru.loginTitle })).toBeInTheDocument();
  });

  it('renders a Russian 404 for an unknown path', () => {
    renderAt('/this-route-does-not-exist');
    expect(screen.getByRole('heading', { name: ru.notFoundTitle })).toBeInTheDocument();
  });
});
