import { describe, expect, it } from 'vitest';
import { scoreDistributionBuckets } from './score-distribution';

describe('scoreDistributionBuckets', () => {
  it('returns ten empty buckets for no data', () => {
    const buckets = scoreDistributionBuckets([]);
    expect(buckets).toHaveLength(10);
    expect(buckets.every((bucket) => bucket.value === 0)).toBe(true);
    expect(buckets[0]?.label).toBe('0-10%');
    expect(buckets[9]?.label).toBe('90-100%');
  });

  it('drops a null (no-session) trainee and buckets everyone else', () => {
    const buckets = scoreDistributionBuckets([5, 15, null, 95, 100]);
    expect(buckets[0]?.value).toBe(1); // 5
    expect(buckets[1]?.value).toBe(1); // 15
    expect(buckets[9]?.value).toBe(2); // 95, 100 (100 clamped into the last bucket)
    expect(buckets.reduce((sum, bucket) => sum + bucket.value, 0)).toBe(4);
  });
});
