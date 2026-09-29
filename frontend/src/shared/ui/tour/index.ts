// I7 E56: the in-app tutorial — guided tours per role, the first-login card and beginner hints.
export type { TourStep } from './types';
export { useTourStore, stepPageMatches, segmentIndexForPath } from './tour-store';
export { useTourPreferences, useTourSeen, useHintsEnabled } from './tour-preferences';
export { TourHost, TARGET_WAIT_MS, placePopover, fitBox, findTourTarget } from './tour-host';
export { TourButton, FirstLoginCard, UserMenu, useFirstLoginCardShown } from './tour-controls';
export { Hint } from './hint';
export { TOUR_BY_ROLE, TRAINEE_TOUR, INSTRUCTOR_TOUR, ADMIN_TOUR, tourPlanFor } from './tours';
