// Hands a fetched file to the browser as a download (I4 E33, the «Скачать CSV» buttons). The
// file is fetched with the bearer token first (`getLessonReportCsv`, `getTraineeStatisticsCsv`),
// because a plain `<a href>` cannot carry one.
//
// I7 E46c root cause (S12.04/S13.28 failed on BASE too, `page.waitForEvent('download')` never
// firing about half the time — measured with a Playwright probe against this exact page, 5/10
// runs timed out before the fix): `anchor.click()` only SCHEDULES the browser's download, it does
// not start it before the call returns, so revoking the object URL on the very next line was a
// race — the browser sometimes read the (by then revoked) blob URL and silently produced no
// download at all. `materials-list.tsx`'s own anchor code already revoked after a delay and never
// showed the bug; this helper now does the same, and every download in the app goes through it
// (`downloadBlob`/`reportDownloadFailed` below), so the fix and the confirmation toast (owner item
// 7, S12) live in one place.
import { toast } from 'sonner';
import { problemMessageRu, type ProblemCode } from '@/shared/api';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from './api';

function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Long enough for the browser to have started reading the blob; matches the delay
  // `report-audio.ts` and `materials-list.tsx` already use for their own object URLs.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

/** Every download the UI starts — materials, CSV/Excel/PDF exports, a scenario version's
 * YAML/JSON, a profile export — goes through this one function, so it always gets the fixed
 * `saveBlob` behaviour above and the confirmation toast once the browser has been handed the
 * file. */
export function downloadBlob(blob: Blob, fileName: string): void {
  saveBlob(blob, fileName);
  toast.success(`Файл «${fileName}» скачан`);
}

/** The failure half of `downloadBlob`: the fetch that would have produced the blob failed before
 * there was anything to hand the browser. `fallbackRu` matches whatever a caller already shows
 * inline for a non-`ProblemError` failure (most show `ru.problemUnknown`; a couple show their own
 * more specific text). */
export function reportDownloadFailed(fileName: string, error: unknown, fallbackRu: string = ru.problemUnknown): void {
  const reasonRu = error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : fallbackRu;
  toast.error(`Не удалось скачать файл «${fileName}»: ${reasonRu}`);
}
