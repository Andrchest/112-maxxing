// I7 E46b (owner item 6): «Скачать Excel» / «Скачать PDF» — the session report never had a CSV.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionReportExportButtons } from './session-report-export-buttons';
import { ru } from '@/shared/i18n/ru';
import { setAuthToken } from '@/shared/lib/api';

describe('SessionReportExportButtons', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    setAuthToken(null);
  });

  it('offers only Excel and PDF, never a CSV button', () => {
    render(<SessionReportExportButtons sessionId="sess-1" />);
    expect(screen.getByRole('button', { name: ru.reportDownloadExcel })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: ru.reportDownloadPdf })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: ru.lessonReportDownloadCsv })).not.toBeInTheDocument();
  });

  it('downloads the session report export with the bearer token, `?format=xlsx` or `?format=pdf`', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const contentType = url.includes('format=pdf')
        ? 'application/pdf'
        : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
      return new Response('x', { status: 200, headers: { 'content-type': contentType } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
    URL.createObjectURL = vi.fn(() => 'blob:session-report');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    setAuthToken('jwt-token');

    try {
      render(<SessionReportExportButtons sessionId="sess-1" />);
      const user = userEvent.setup();

      await user.click(screen.getByRole('button', { name: ru.reportDownloadExcel }));
      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      const [xlsxUrl, xlsxInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
      expect(xlsxUrl).toBe('/api/v1/reports/sess-1/export?format=xlsx');
      expect((xlsxInit.headers as Record<string, string>).Authorization).toBe('Bearer jwt-token');

      await user.click(screen.getByRole('button', { name: ru.reportDownloadPdf }));
      await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
      const [pdfUrl] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
      expect(pdfUrl).toBe('/api/v1/reports/sess-1/export?format=pdf');
    } finally {
      URL.createObjectURL = original.create;
      URL.revokeObjectURL = original.revoke;
    }
  });

  it('shows the problem when the export is refused', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ title: 'Conflict', status: 409, code: 'REPORT_NOT_READY' }), {
            status: 409,
            headers: { 'content-type': 'application/problem+json' },
          }),
      ),
    );
    render(<SessionReportExportButtons sessionId="sess-1" />);
    await userEvent.setup().click(screen.getByRole('button', { name: ru.reportDownloadExcel }));
    expect(await screen.findByRole('alert')).toHaveTextContent(ru.problemReportNotReady);
  });
});
