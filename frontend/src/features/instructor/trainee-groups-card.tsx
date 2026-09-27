// I3 E9a (70 §70.3.7, F-15 «Назначать учащимся конкретные задания и группы»): the instructor's
// trainee groups — a name and a set of trainees, created, renamed, re-staffed and deleted here.
// A lesson form offers every group; picking one pre-fills the lesson's participants. Deleting a
// group changes no lesson (the server keeps each lesson's own participants).
// I5 E39 (Q-E9b-4 variant а): every instructor sees and uses every group, but only its creator
// (`TraineeGroup.created_by_user_id`) or an ADMIN edits or deletes it — for anyone else those two
// buttons are disabled with «Изменять может только преподаватель, создавший группу».
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { canChangeOwned, useAuthStore } from '@/entities/session';
import { ProblemError } from '@/shared/lib/api';
import {
  createTraineeGroup,
  deleteTraineeGroup,
  listTraineeGroups,
  listUsers,
  problemMessageRu,
  queryKeys,
  updateTraineeGroup,
  type ProblemCode,
  type TraineeGroup,
} from '@/shared/api';

interface Draft {
  /** `null` while creating a new group. */
  groupId: string | null;
  name: string;
  memberIds: string[];
}

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

export function TraineeGroupsCard() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const [draft, setDraft] = useState<Draft | null>(null);

  const groupsQuery = useQuery({ queryKey: queryKeys.traineeGroups.list(), queryFn: listTraineeGroups });
  const traineesQuery = useQuery({
    queryKey: queryKeys.users.list('TRAINEE'),
    queryFn: () => listUsers({ role: 'TRAINEE' }),
  });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.traineeGroups.list() });
  }

  const saveMutation = useMutation({
    mutationFn: (value: Draft) => {
      const body = { name_ru: value.name.trim(), member_user_ids: value.memberIds };
      return value.groupId ? updateTraineeGroup(value.groupId, body) : createTraineeGroup(body);
    },
    onSuccess: () => {
      setDraft(null);
      refresh();
    },
  });

  const deleteMutation = useMutation({ mutationFn: deleteTraineeGroup, onSuccess: refresh });

  function edit(group: TraineeGroup) {
    saveMutation.reset();
    setDraft({ groupId: group.group_id, name: group.name_ru, memberIds: group.members.map((member) => member.user_id) });
  }

  function toggleMember(userId: string) {
    setDraft((current) =>
      current
        ? {
            ...current,
            memberIds: current.memberIds.includes(userId)
              ? current.memberIds.filter((id) => id !== userId)
              : [...current.memberIds, userId],
          }
        : current,
    );
  }

  return (
    <Card className="max-w-2xl" data-slot="trainee-groups">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <h2 className="font-heading text-base leading-snug font-medium">{t('traineeGroupsTitle')}</h2>
        {draft === null ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              saveMutation.reset();
              setDraft({ groupId: null, name: '', memberIds: [] });
            }}
          >
            {t('traineeGroupCreateButton')}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {draft ? (
          <div className="flex flex-col gap-2 rounded-md border border-border p-2" data-slot="trainee-group-form">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="trainee-group-name">{t('traineeGroupNameLabel')}</Label>
              <Input
                id="trainee-group-name"
                value={draft.name}
                placeholder={t('traineeGroupNamePlaceholder')}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </div>
            <fieldset className="flex flex-col gap-1">
              <legend className="text-sm font-medium">{t('traineeGroupMembersLabel')}</legend>
              {(traineesQuery.data?.items ?? []).map((account) => (
                <label key={account.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4 accent-primary"
                    checked={draft.memberIds.includes(account.id)}
                    onChange={() => toggleMember(account.id)}
                  />
                  {account.display_name_ru}
                </label>
              ))}
            </fieldset>
            {saveMutation.error ? (
              <p role="alert" className="text-sm text-destructive">
                {problemText(saveMutation.error)}
              </p>
            ) : null}
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => saveMutation.mutate(draft)}
                disabled={draft.name.trim() === '' || saveMutation.isPending}
              >
                {draft.groupId ? t('traineeGroupSaveButton') : t('traineeGroupCreateButton')}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => setDraft(null)}>
                {t('traineeGroupCancelButton')}
              </Button>
            </div>
          </div>
        ) : null}

        {groupsQuery.isLoading ? <p className="text-sm text-muted-foreground">{t('traineeGroupsLoading')}</p> : null}
        {groupsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(groupsQuery.error)}
          </p>
        ) : null}
        {groupsQuery.data && groupsQuery.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('traineeGroupsEmpty')}</p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {(groupsQuery.data?.items ?? []).map((group) => {
            const canChange = canChangeOwned(user, group.created_by_user_id);
            return (
              <li
                key={group.group_id}
                className="flex items-center justify-between gap-2 rounded-md border border-border p-2"
                data-slot="trainee-group-row"
              >
                <div>
                  <p className="text-sm font-medium">{group.name_ru}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('traineeGroupMembersPrefix')}:{' '}
                    {group.members.length > 0
                      ? group.members.map((member) => member.display_name_ru).join(', ')
                      : t('traineeGroupNoMembers')}
                  </p>
                  {!canChange ? (
                    <p className="text-xs text-muted-foreground" data-slot="ownership-hint">
                      {t('ownershipHintGroup')}
                    </p>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => edit(group)} disabled={!canChange}>
                    {t('traineeGroupEditButton')}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => deleteMutation.mutate(group.group_id)}
                    disabled={deleteMutation.isPending || !canChange}
                  >
                    {t('traineeGroupDeleteButton')}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
        {deleteMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(deleteMutation.error)}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
