// Route: /instructor/materials (I4 E34, HLD 71 §71.11, ТЗ ¶227, ¶387, ¶370). «Материалы»:
// upload a methodical material and archive one; the list itself (with the "include archived"
// toggle) is the same `MaterialsList` the trainee's «Справочная база» reads.
import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ru } from '@/shared/i18n/ru';
import { ProblemError } from '@/shared/lib/api';
import { problemMessageRu, queryKeys, uploadMaterial, type ProblemCode, type UserRole } from '@/shared/api';
import { useAuthStore } from '@/entities/session';
import { MaterialsList } from '@/features/materials/materials-list';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

function UploadMaterialForm() {
  const queryClient = useQueryClient();
  const [titleRu, setTitleRu] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadMutation = useMutation({
    mutationFn: (input: { titleRu: string; file: File }) => uploadMaterial(input.titleRu, input.file),
    onSuccess: () => {
      setTitleRu('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(true) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(false) });
    },
  });

  function submit() {
    const file = fileInputRef.current?.files?.[0];
    if (!file || titleRu.trim() === '') return;
    uploadMutation.mutate({ titleRu: titleRu.trim(), file });
  }

  return (
    <Card data-slot="materials-upload" data-tour="materials-upload">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('materialsInstructorTitle')}</h2>
      </CardHeader>
      <CardContent className="@container flex flex-col gap-3">
        <div className="grid gap-3 @lg:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="material-title">{t('materialsUploadTitleLabel')}</Label>
            <Input id="material-title" value={titleRu} onChange={(event) => setTitleRu(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="material-file">{t('materialsUploadFileLabel')}</Label>
            <input id="material-file" ref={fileInputRef} type="file" className="text-sm" />
          </div>
        </div>
        {uploadMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(uploadMutation.error)}
          </p>
        ) : null}
        <div>
          <Button type="button" size="sm" onClick={submit} disabled={uploadMutation.isPending}>
            {t('materialsUploadButton')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function MaterialsPage() {
  const user = useAuthStore((state) => state.user);
  const roleLabel = user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined;

  return (
    <AppShell title={t('materialsInstructorTitle')} role={roleLabel} userLabel={user?.display_name_ru}>
      <h1 className="text-lg font-semibold tracking-tight">{t('materialsInstructorTitle')}</h1>
      <div className="mt-4 flex flex-col gap-4">
        <UploadMaterialForm />
        <MaterialsList canManage />
      </div>
    </AppShell>
  );
}
