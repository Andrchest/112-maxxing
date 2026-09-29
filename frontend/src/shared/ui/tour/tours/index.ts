// I7 E56: which tour a role gets, and where the header «Обучение» button starts it.
import type { UserRole } from '@/shared/api';
import type { TourStep } from '../types';
import { segmentIndexForPath } from '../tour-store';
import { ADMIN_TOUR } from './admin';
import { INSTRUCTOR_TOUR } from './instructor';
import { TRAINEE_TOUR } from './trainee';

export { ADMIN_TOUR, INSTRUCTOR_TOUR, TRAINEE_TOUR };

export const TOUR_BY_ROLE: Record<UserRole, readonly TourStep[]> = {
  TRAINEE: TRAINEE_TOUR,
  INSTRUCTOR: INSTRUCTOR_TOUR,
  ADMIN: ADMIN_TOUR,
};

/**
 * The tour and first step for `role` on `pathname`: the role's tour from this page's own segment,
 * else from its beginning. An administrator on an instructor page (the `/instructor/*` guard admits
 * ADMIN too) gets the instructor tour's segment for that page, which the admin tour does not cover.
 */
export function tourPlanFor(role: UserRole, pathname: string): { steps: readonly TourStep[]; index: number } {
  const own = TOUR_BY_ROLE[role];
  const ownIndex = segmentIndexForPath(own, pathname);
  if (ownIndex >= 0) return { steps: own, index: ownIndex };
  if (role === 'ADMIN') {
    const instructorIndex = segmentIndexForPath(INSTRUCTOR_TOUR, pathname);
    if (instructorIndex >= 0) return { steps: INSTRUCTOR_TOUR, index: instructorIndex };
  }
  return { steps: own, index: 0 };
}
