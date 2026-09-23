// Pure display formatting for a server ISO-8601 UTC timestamp (D7: "timestamps render as local
// «ДД.ММ.ГГГГ ЧЧ:ММ:СС», never ISO"). `Date`'s own getters (`getDate`/`getHours`/…) already read
// the browser's local time zone — no manual offset math, no library.
export function formatTimestampRu(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
