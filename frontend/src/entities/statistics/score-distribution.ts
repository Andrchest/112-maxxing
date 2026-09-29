// «Распределение итоговых баллов» (I7 E46a, owner item 6): 10 %-wide buckets of the current
// filter's `TraineeStatisticsRow.average_percent`, purely client-side — the bar chart on the
// instructor statistics page needs no backend change, since `average_percent` is already on the
// page (`getTraineeStatistics`, D11). A trainee with no session (`average_percent: null`) is
// excluded, exactly like `formatPercent`'s own «—» reading of that value.
export interface ScoreBucket {
  key: string;
  label: string;
  value: number;
}

const BUCKET_COUNT = 10;
const BUCKET_WIDTH = 100 / BUCKET_COUNT;

export function scoreDistributionBuckets(percents: readonly (number | null)[]): ScoreBucket[] {
  const counts = new Array(BUCKET_COUNT).fill(0) as number[];
  for (const percent of percents) {
    if (percent === null) continue;
    const clamped = Math.max(0, Math.min(100, percent));
    const index = clamped >= 100 ? BUCKET_COUNT - 1 : Math.floor(clamped / BUCKET_WIDTH);
    counts[index] = (counts[index] ?? 0) + 1;
  }
  return counts.map((count, index) => ({
    key: String(index),
    label: `${index * BUCKET_WIDTH}-${(index + 1) * BUCKET_WIDTH}%`,
    value: count,
  }));
}
