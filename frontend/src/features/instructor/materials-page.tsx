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

// I7 E46c (owner item 6): a title per file makes no sense for several files at once, so a batch
// (more than one file chosen) ignores «Название» and titles each material after its own file name
// (extension stripped) — a single file keeps the exact previous behaviour (the typed title, one
// `uploadMaterial` call). Materials have no version concept, so a batch result is only «загружен»
// or «ошибка: <reason>», never «новая версия».
interface MaterialBatchResult {
  fileName: string;
  status: 'uploaded' | 'error';
  detailRu?: string;
}

function titleOfFileName(fileName: string): string {
  const dot = fileName.lastIndexOf('.');
  const stem = dot > 0 ? fileName.slice(0, dot) : fileName;
  return stem.trim() || fileName;
}

function materialBatchResultLabel(result: MaterialBatchResult): string {
  if (result.status === 'uploaded') return t('uploadBatchUploadedRu');
  return `${t('uploadBatchErrorPrefixRu')}: ${result.detailRu ?? t('problemUnknown')}`;
}

function UploadMaterialForm() {
  const queryClient = useQueryClient();
  const [titleRu, setTitleRu] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileCount, setFileCount] = useState(0);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResults, setBatchResults] = useState<MaterialBatchResult[] | null>(null);

  function invalidateMaterials(): void {
    void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(true) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(false) });
  }

  const uploadMutation = useMutation({
    mutationFn: (input: { titleRu: string; file: File }) => uploadMaterial(input.titleRu, input.file),
    onSuccess: () => {
      setTitleRu('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      setFileCount(0);
      invalidateMaterials();
    },
  });

  async function runBatchUpload(files: File[]): Promise<void> {
    setBatchRunning(true);
    setBatchResults(null);
    const results: MaterialBatchResult[] = [];
    for (const file of files) {
      try {
        await uploadMaterial(titleOfFileName(file.name), file);
        results.push({ fileName: file.name, status: 'uploaded' });
      } catch (error) {
        results.push({ fileName: file.name, status: 'error', detailRu: problemText(error) });
      }
    }
    setBatchResults(results);
    setBatchRunning(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
    setFileCount(0);
    invalidateMaterials();
  }

  function submit() {
    const files = fileInputRef.current?.files;
    if (!files || files.length === 0) return;
    if (files.length === 1) {
      const file = files[0];
      if (!file || titleRu.trim() === '') return;
      uploadMutation.mutate({ titleRu: titleRu.trim(), file });
      return;
    }
    void runBatchUpload(Array.from(files));
  }

  const isBatch = fileCount > 1;

  return (
    <Card data-slot="materials-upload" data-tour="materials-upload">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('materialsInstructorTitle')}</h2>
      </CardHeader>
      <CardContent className="@container flex flex-col gap-3">
        <div className="grid gap-3 @lg:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="material-title">{t('materialsUploadTitleLabel')}</Label>
            <Input id="material-title" value={titleRu} onChange={(event) => setTitleRu(event.target.value)} disabled={isBatch} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="material-file">{t('materialsUploadFileLabel')}</Label>
            <input
              id="material-file"
              ref={fileInputRef}
              type="file"
              className="text-sm"
              multiple
              onChange={(event) => {
                setBatchResults(null);
                setFileCount(event.target.files?.length ?? 0);
              }}
            />
          </div>
        </div>
        {isBatch ? <p className="text-xs text-muted-foreground">{t('materialsBatchFileCount').replace('{n}', String(fileCount))}</p> : null}
        {uploadMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(uploadMutation.error)}
          </p>
        ) : null}
        <div>
          <Button type="button" size="sm" onClick={submit} disabled={uploadMutation.isPending || batchRunning}>
            {batchRunning ? t('materialsBatchUploading') : t('materialsUploadButton')}
          </Button>
        </div>
        {batchResults ? (
          <div className="rounded-md border border-border p-2 text-sm">
            <ul className="flex flex-col gap-1">
              {batchResults.map((result, index) => (
                <li key={`${result.fileName}-${index}`} className="text-xs text-muted-foreground">
                  {result.fileName} — {materialBatchResultLabel(result)}
                </li>
              ))}
            </ul>
            <p className="mt-1 text-sm font-medium">
              {t('uploadBatchSummaryRu')
                .replace('{done}', String(batchResults.filter((result) => result.status !== 'error').length))
                .replace('{total}', String(batchResults.length))}
            </p>
          </div>
        ) : null}
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
