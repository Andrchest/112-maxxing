// «Пользователи» tab (I4 E30, 71 §71.7 → E28, 71 §71.5). Create an account of any role, block or
// unblock one, change its role, or reset its password — the self/last-admin guards and the
// argon2/min-length rules all live server-side (E28); this only offers the controls and shows
// whatever `ProblemError` the server sends back.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/shared/ui/dialog';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { formatTimestampRu } from '@/shared/lib/format-timestamp';
import { downloadBlob, reportDownloadFailed } from '@/shared/lib/download';
import {
  createUser,
  exportUserProfile,
  listUsers,
  problemMessageRu,
  queryKeys,
  resetUserPassword,
  updateUser,
  type ProblemCode,
  type UserAccountI4,
  type UserRole,
} from '@/shared/api';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};
const USER_ROLES: UserRole[] = ['TRAINEE', 'INSTRUCTOR', 'ADMIN'];

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

function CreateUserDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [displayNameRu, setDisplayNameRu] = useState('');
  const [role, setRole] = useState<UserRole>('TRAINEE');
  const [password, setPassword] = useState('');

  const createMutation = useMutation({
    mutationFn: () => createUser({ username, display_name_ru: displayNameRu, user_role: role, password }),
    onSuccess: () => {
      setOpen(false);
      setUsername('');
      setDisplayNameRu('');
      setRole('TRAINEE');
      setPassword('');
      onCreated();
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) createMutation.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm" data-tour="admin-users-create">
          {t('adminUsersCreateButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('adminUsersCreateTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-user-username">{t('adminUsersUsernameLabel')}</Label>
            <Input id="admin-user-username" value={username} onChange={(event) => setUsername(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-user-display-name">{t('adminUsersDisplayNameLabel')}</Label>
            <Input id="admin-user-display-name" value={displayNameRu} onChange={(event) => setDisplayNameRu(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-user-role">{t('adminUsersRoleLabel')}</Label>
            <select
              id="admin-user-role"
              className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              value={role}
              onChange={(event) => setRole(event.target.value as UserRole)}
            >
              {USER_ROLES.map((candidate) => (
                <option key={candidate} value={candidate}>
                  {t(USER_ROLE_LABEL_KEY[candidate])}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admin-user-password">{t('adminUsersPasswordLabel')}</Label>
            <Input
              id="admin-user-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {createMutation.error ? (
            <p role="alert" className="text-sm text-destructive">
              {problemText(createMutation.error)}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={createMutation.isPending} onClick={() => setOpen(false)}>
            {t('adminUsersCancelButton')}
          </Button>
          <Button
            type="button"
            disabled={createMutation.isPending || username.trim() === '' || displayNameRu.trim() === '' || password === ''}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? t('adminUsersCreating') : t('adminUsersCreateSubmit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user }: { user: UserAccountI4 }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');

  const resetMutation = useMutation({
    mutationFn: () => resetUserPassword(user.id, { password }),
    onSuccess: () => {
      setOpen(false);
      setPassword('');
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) resetMutation.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="outline">
          {t('adminUsersResetPasswordButton')}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('adminUsersResetPasswordTitle')}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`admin-user-reset-${user.id}`}>{t('adminUsersPasswordLabel')}</Label>
          <Input
            id={`admin-user-reset-${user.id}`}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {resetMutation.error ? (
            <p role="alert" className="text-sm text-destructive">
              {problemText(resetMutation.error)}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={resetMutation.isPending} onClick={() => setOpen(false)}>
            {t('adminUsersCancelButton')}
          </Button>
          <Button type="button" disabled={resetMutation.isPending || password === ''} onClick={() => resetMutation.mutate()}>
            {resetMutation.isPending ? t('adminUsersSaving') : t('adminUsersResetPasswordSubmit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// I5 E37 (Q-E16-4): «Скачать профиль (JSON)» — account fields plus the E33 history summary for a
// trainee, never the password hash or SIP HA1. ADMIN may download anyone's; the server enforces it
// (`403 FORBIDDEN_FOR_ROLE`), this button is just always shown here since every row's viewer is ADMIN.
function DownloadProfileButton({ user }: { user: UserAccountI4 }) {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    const fileName = `profile-${user.username}.json`;
    try {
      downloadBlob(await exportUserProfile(user.id), fileName);
    } catch (caught) {
      setError(caught);
      reportDownloadFailed(fileName, caught);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button type="button" size="sm" variant="outline" disabled={downloading} onClick={() => void handleDownload()}>
        {downloading ? t('profileExportDownloading') : t('adminUsersDownloadProfileButton')}
      </Button>
      {error ? (
        <span role="alert" className="text-xs text-destructive">
          {problemText(error)}
        </span>
      ) : null}
    </div>
  );
}

export function UsersTab() {
  const queryClient = useQueryClient();
  const [roleFilter, setRoleFilter] = useState<UserRole | ''>('');
  const [includeInactive, setIncludeInactive] = useState(false);
  const [search, setSearch] = useState('');

  const usersQuery = useQuery({
    queryKey: queryKeys.admin.users(roleFilter || undefined, includeInactive),
    queryFn: () => listUsers({ role: roleFilter || undefined, includeInactive }),
  });

  function invalidateUsers() {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
  }

  const updateMutation = useMutation({
    mutationFn: (input: { userId: string; body: Parameters<typeof updateUser>[1] }) => updateUser(input.userId, input.body),
    onSuccess: invalidateUsers,
  });

  // I6 FIX1: every page is loaded (`listUsers` walks them), newest account first, so a just-created
  // user is on top; «Поиск по логину» narrows by a case-insensitive substring of the login.
  const allUsers = usersQuery.data?.items ?? [];
  const needle = search.trim().toLowerCase();
  const users = allUsers
    .filter((row) => needle === '' || row.username.toLowerCase().includes(needle))
    .sort((left, right) => right.created_at.localeCompare(left.created_at) || left.username.localeCompare(right.username));

  return (
    <Card data-slot="admin-users">
      <CardHeader className="flex flex-row flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-users-role-filter">{t('adminUsersRoleLabel')}</Label>
          <select
            id="admin-users-role-filter"
            className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            value={roleFilter}
            onChange={(event) => setRoleFilter(event.target.value as UserRole | '')}
          >
            <option value="">{t('adminUsersRoleFilterAll')}</option>
            {USER_ROLES.map((candidate) => (
              <option key={candidate} value={candidate}>
                {t(USER_ROLE_LABEL_KEY[candidate])}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-users-search">{t('adminUsersSearchLabel')}</Label>
          <Input
            id="admin-users-search"
            type="search"
            className="w-56"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={includeInactive}
            onChange={(event) => setIncludeInactive(event.target.checked)}
          />
          {t('adminUsersIncludeInactiveLabel')}
        </label>
        <div className="ml-auto">
          <CreateUserDialog onCreated={invalidateUsers} />
        </div>
      </CardHeader>
      <CardContent>
        {usersQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(usersQuery.error)}
          </p>
        ) : null}
        {updateMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(updateMutation.error)}
          </p>
        ) : null}
        {usersQuery.data && allUsers.length === 0 ? <p className="text-sm text-muted-foreground">{t('adminUsersEmpty')}</p> : null}
        {allUsers.length > 0 && users.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('adminUsersSearchEmpty')}</p>
        ) : null}
        {users.length > 0 ? (
          <p className="mb-2 text-xs text-muted-foreground" data-slot="admin-users-count">
            {t('adminUsersCountLabel')}: {users.length} / {allUsers.length}
          </p>
        ) : null}
        {users.length > 0 ? (
          <table className="w-full border-collapse text-sm" data-slot="admin-users-table">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="p-2 font-medium">{t('adminUsersColumnUsername')}</th>
                <th className="p-2 font-medium">{t('adminUsersColumnDisplayName')}</th>
                <th className="p-2 font-medium">{t('adminUsersColumnRole')}</th>
                <th className="p-2 font-medium">{t('adminUsersColumnStatus')}</th>
                <th className="p-2 font-medium">{t('adminUsersColumnCreatedAt')}</th>
                <th className="p-2 font-medium">{t('adminUsersColumnActions')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((row) => (
                <tr key={row.id} className="border-b border-border/60 align-top" data-slot="admin-user-row">
                  <td className="p-2">{row.username}</td>
                  <td className="p-2">{row.display_name_ru}</td>
                  <td className="p-2">
                    <select
                      aria-label={t('adminUsersColumnRole')}
                      className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                      value={row.user_role}
                      disabled={updateMutation.isPending}
                      onChange={(event) =>
                        updateMutation.mutate({ userId: row.id, body: { user_role: event.target.value as UserRole } })
                      }
                    >
                      {USER_ROLES.map((candidate) => (
                        <option key={candidate} value={candidate}>
                          {t(USER_ROLE_LABEL_KEY[candidate])}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-2">{row.is_active ? t('adminUsersStatusActive') : t('adminUsersStatusBlocked')}</td>
                  <td className="p-2 tabular-nums">{formatTimestampRu(row.created_at)}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={updateMutation.isPending}
                        onClick={() => updateMutation.mutate({ userId: row.id, body: { is_active: !row.is_active } })}
                      >
                        {row.is_active ? t('adminUsersBlockButton') : t('adminUsersUnblockButton')}
                      </Button>
                      <ResetPasswordDialog user={row} />
                      <DownloadProfileButton user={row} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </CardContent>
    </Card>
  );
}
