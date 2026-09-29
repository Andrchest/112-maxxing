// I7 E46c: the shared download helper. `downloadBlob` is every download's single entry point
// (materials, CSV/Excel/PDF exports, a scenario version's YAML/JSON, a profile export) — this
// covers the fixed S12.04/S13.28 anchor flow plus the confirmation toast pair (owner item 7).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from './api';
import { downloadBlob, reportDownloadFailed } from './download';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe('downloadBlob', () => {
  let createObjectURL: (obj: Blob | MediaSource) => string;
  let revokeObjectURL: (url: string) => void;
  let click: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    createObjectURL = vi.fn(() => 'blob:file');
    revokeObjectURL = vi.fn();
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
    click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    click.mockRestore();
    vi.clearAllMocks();
  });

  it('clicks an anchor attached to the document and confirms with a toast', () => {
    downloadBlob(new Blob(['x']), 'report.csv');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith('Файл «report.csv» скачан');
  });

  it('does not revoke the object URL before the browser had a chance to read it', () => {
    downloadBlob(new Blob(['x']), 'report.csv');

    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(30000);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:file');
  });
});

describe('reportDownloadFailed', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows the problem message for a ProblemError', () => {
    const error = new ProblemError({ type: 'about:blank', title: 'x', status: 422, code: 'MATERIAL_TYPE_NOT_ALLOWED' }, 422);

    reportDownloadFailed('virus.exe', error);

    expect(toast.error).toHaveBeenCalledWith(`Не удалось скачать файл «virus.exe»: ${ru.problemMaterialTypeNotAllowed}`);
  });

  it('falls back to the generic message for a non-problem error', () => {
    reportDownloadFailed('report.csv', new Error('network down'));

    expect(toast.error).toHaveBeenCalledWith(`Не удалось скачать файл «report.csv»: ${ru.problemUnknown}`);
  });

  it('takes a caller-supplied fallback for a non-problem error', () => {
    reportDownloadFailed('clip.mp3', new Error('network down'), ru.reportAudioLoadFailed);

    expect(toast.error).toHaveBeenCalledWith(`Не удалось скачать файл «clip.mp3»: ${ru.reportAudioLoadFailed}`);
  });
});
