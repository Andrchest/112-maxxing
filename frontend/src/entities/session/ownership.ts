// I5 E39 (Q-E9b-4 variant а): an instructor sees every lesson, session and group but changes only
// the ones they created; an ADMIN changes any. The server is the rule (`403 NOT_RESOURCE_OWNER`);
// this mirrors it so a control the server would refuse is shown disabled with a hint instead.
import type { UserAccount } from '@/shared/api';

/** May `user` change a resource whose owner is `createdByUserId`? `null`/`undefined` owner =
 * a legacy row with no recorded owner, which any instructor may change. */
export function canChangeOwned(user: UserAccount | null | undefined, createdByUserId: string | null | undefined): boolean {
  if (!user) return false;
  if (user.user_role === 'ADMIN') return true;
  if (user.user_role !== 'INSTRUCTOR') return false;
  return createdByUserId == null || createdByUserId === user.id;
}
