import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MaterialsPage } from './materials-page';
import { ru } from '@/shared/i18n/ru';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

function problemResponse(code: string, status: number): Response {
  return new Response(JSON.stringify({ type: 'about:blank', title: code, status, code }), {
    status,
    headers: { 'content-type': 'application/problem+json' },
  });
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <MaterialsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('MaterialsPage — instructor materials management (I4 E34, HLD 71 §71.11)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uploads a material, lists it and archives it', async () => {
    const user = userEvent.setup();
    let materials: Record<string, unknown>[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/materials' && method === 'GET') {
        return jsonResponse({ items: materials });
      }
      if (url === '/api/v1/materials' && method === 'POST') {
        const body = init?.body as FormData;
        const material = {
          material_id: 'mat-1',
          title_ru: String(body.get('title_ru')),
          file_name: (body.get('file') as File).name,
          content_type: 'application/pdf',
          size_bytes: 5,
          sha256: 'a'.repeat(64),
          uploaded_by_user_id: 'instr-1',
          created_at: '2026-09-25T00:00:00Z',
          archived_at: null,
        };
        materials = [material];
        return jsonResponse(material, 201);
      }
      if (url === '/api/v1/materials/mat-1/archive' && method === 'POST') {
        materials = materials.map((material) => ({ ...material, archived_at: '2026-09-25T01:00:00Z' }));
        return jsonResponse(materials[0]);
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    expect(await screen.findByText(ru.materialsEmpty)).toBeInTheDocument();

    await user.type(screen.getByLabelText(ru.materialsUploadTitleLabel), 'Manual A');
    const file = new File(['%PDF-1.4'], 'manual.pdf', { type: 'application/pdf' });
    await user.upload(screen.getByLabelText(ru.materialsUploadFileLabel), file);
    await user.click(screen.getByRole('button', { name: ru.materialsUploadButton }));

    expect(await screen.findByText('Manual A')).toBeInTheDocument();
    expect(screen.getByText('manual.pdf')).toBeInTheDocument();

    const uploadCall = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === '/api/v1/materials' && (init as RequestInit | undefined)?.method === 'POST',
    );
    expect(uploadCall).toBeDefined();
    expect((uploadCall![1] as RequestInit).body).toBeInstanceOf(FormData);

    await user.click(screen.getByRole('button', { name: ru.materialsArchiveButton }));
    await waitFor(() => expect(screen.getByText(`manual.pdf · ${ru.materialsArchivedBadge}`)).toBeInTheDocument());
  });

  // I7 E46c (owner item 6): several files at once upload one after another, titled after their
  // own file names; one bad file never stops the rest and the summary counts only the good ones.
  it('uploads several files at once, one bad file does not stop the rest', async () => {
    const user = userEvent.setup();
    let nextId = 1;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/materials' && method === 'GET') return jsonResponse({ items: [] });
      if (url === '/api/v1/materials' && method === 'POST') {
        const body = init?.body as FormData;
        const file = body.get('file') as File;
        if (file.name === 'bad.exe') return problemResponse('MATERIAL_TYPE_NOT_ALLOWED', 422);
        const material = {
          material_id: `mat-${nextId++}`,
          title_ru: String(body.get('title_ru')),
          file_name: file.name,
          content_type: 'application/pdf',
          size_bytes: 5,
          sha256: 'a'.repeat(64),
          uploaded_by_user_id: 'instr-1',
          created_at: '2026-09-25T00:00:00Z',
          archived_at: null,
        };
        return jsonResponse(material, 201);
      }
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    await screen.findByText(ru.materialsEmpty);

    await user.upload(screen.getByLabelText(ru.materialsUploadFileLabel), [
      new File(['%PDF-1.4'], 'first.pdf', { type: 'application/pdf' }),
      new File(['MZ'], 'bad.exe', { type: 'application/octet-stream' }),
      new File(['%PDF-1.4'], 'third.pdf', { type: 'application/pdf' }),
    ]);
    await user.click(screen.getByRole('button', { name: ru.materialsUploadButton }));

    const summary = ru.uploadBatchSummaryRu.replace('{done}', '2').replace('{total}', '3');
    expect(await screen.findByText(summary)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`bad\\.exe.*${ru.uploadBatchErrorPrefixRu}`))).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(ru.uploadBatchUploadedRu))).toHaveLength(2);
  });

  it('shows the Russian message for a refused upload', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url === '/api/v1/materials' && method === 'GET') return jsonResponse({ items: [] });
      if (url === '/api/v1/materials' && method === 'POST') return problemResponse('MATERIAL_TYPE_NOT_ALLOWED', 422);
      throw new Error(`unexpected fetch: ${method} ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();
    await screen.findByText(ru.materialsEmpty);

    await user.type(screen.getByLabelText(ru.materialsUploadTitleLabel), 'Virus');
    const file = new File(['MZ'], 'virus.exe', { type: 'application/octet-stream' });
    await user.upload(screen.getByLabelText(ru.materialsUploadFileLabel), file);
    await user.click(screen.getByRole('button', { name: ru.materialsUploadButton }));

    expect(await screen.findByText(ru.problemMaterialTypeNotAllowed)).toBeInTheDocument();
  });
});
