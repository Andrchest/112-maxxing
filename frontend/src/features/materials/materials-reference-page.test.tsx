import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MaterialsReferencePage } from './materials-reference-page';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

describe('MaterialsReferencePage — the trainee reference base (I4 E34, HLD 71 §71.11)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lists a material read-only, with no archive action', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/v1/materials') {
        return jsonResponse({
          items: [
            {
              material_id: 'mat-1',
              title_ru: 'Manual A',
              file_name: 'manual.pdf',
              content_type: 'application/pdf',
              size_bytes: 5,
              sha256: 'a'.repeat(64),
              uploaded_by_user_id: 'instr-1',
              created_at: '2026-09-25T00:00:00Z',
              archived_at: null,
            },
          ],
        });
      }
      throw new Error(`unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <MaterialsReferencePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Manual A')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.materialsOpenButton })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.materialsArchiveButton })).not.toBeInTheDocument();
    // The trainee's read has no "include archived" toggle (that is the instructor's own page).
    expect(screen.queryByText(ru.materialsShowArchived)).not.toBeInTheDocument();
  });

  // I6 FIX1: a PDF has «Скачать» next to «Открыть» — saved under its own name, no new tab.
  it('downloads a PDF under its file name with the download button, without opening a tab', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/v1/materials') {
        return jsonResponse({
          items: [
            {
              material_id: 'mat-1',
              title_ru: 'Manual A',
              file_name: 'manual.pdf',
              content_type: 'application/pdf',
              size_bytes: 5,
              sha256: 'a'.repeat(64),
              uploaded_by_user_id: 'instr-1',
              created_at: '2026-09-25T00:00:00Z',
              archived_at: null,
            },
          ],
        });
      }
      if (url.startsWith('/api/v1/materials/mat-1')) {
        return new Response('%PDF-1.4', { status: 200, headers: { 'content-type': 'application/pdf' } });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const openSpy = vi.fn();
    vi.stubGlobal('open', openSpy);
    const { createObjectURL: originalCreate, revokeObjectURL: originalRevoke } = URL;
    URL.createObjectURL = vi.fn(() => 'blob:material');
    URL.revokeObjectURL = vi.fn();
    const downloads: string[] = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(this.download);
    });

    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <MaterialsReferencePage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText('Manual A');
    await userEvent.setup().click(screen.getByRole('button', { name: ru.materialsDownloadButton }));

    await waitFor(() => expect(downloads).toEqual(['manual.pdf']));
    expect(openSpy).not.toHaveBeenCalled();
    clickSpy.mockRestore();
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  });
});
