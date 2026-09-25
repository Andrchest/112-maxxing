// Hands a fetched file to the browser as a download (I4 E33, the «Скачать CSV» buttons). The
// file is fetched with the bearer token first (`getLessonReportCsv`, `getTraineeStatisticsCsv`),
// because a plain `<a href>` cannot carry one; the object URL is revoked right after the click.
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
