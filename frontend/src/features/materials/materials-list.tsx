// I4 E34 (HLD 71 §71.11): the shared read of `training_materials`, used by both the instructor's
// «Материалы» page (with the archive action, `canManage`) and the trainee's «Справочная база»
// (read-only). A PDF opens in a new tab (`Content-Disposition: inline` on the server); every
// other allowed type downloads through the browser's own save flow — a plain `<a href>` cannot
// carry the bearer token, so the bytes are fetched here first (`getMaterialFile` → `Blob`).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { t } from '@/shared/i18n';
import { ProblemError } from '@/shared/lib/api';
import {
  archiveMaterial,
  getMaterialFile,
  listMaterials,
  problemMessageRu,
  queryKeys,
  type ProblemCode,
  type TrainingMaterialView,
} from '@/shared/api';

function problemText(error: unknown): string {
  return error instanceof ProblemError ? problemMessageRu(error.code as ProblemCode) : t('problemUnknown');
}

/** Opens a PDF inline (unless `download`), downloads everything else — `URL.revokeObjectURL`
 * after a delay long enough for the browser to have started acting on it (the same margin
 * `report-audio.ts` uses for its own object URLs). I6 FIX1: a PDF also has «Скачать», saving it
 * under its own file name, for a browser (or a tester) that does not show a new tab. */
async function openOrDownload(material: TrainingMaterialView, download = false) {
  const blob = await getMaterialFile(material.material_id);
  const url = URL.createObjectURL(blob);
  if (material.content_type === 'application/pdf' && !download) {
    window.open(url, '_blank', 'noopener');
  } else {
    const link = document.createElement('a');
    link.href = url;
    link.download = material.file_name;
    link.click();
  }
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

interface MaterialsListProps {
  /** INSTRUCTOR/ADMIN: offers the archive action and an "include archived" toggle. */
  canManage: boolean;
}

export function MaterialsList({ canManage }: MaterialsListProps) {
  const queryClient = useQueryClient();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [openError, setOpenError] = useState<unknown>(null);

  const effectiveIncludeArchived = canManage && includeArchived;
  const materialsQuery = useQuery({
    queryKey: queryKeys.materials.list(effectiveIncludeArchived),
    queryFn: () => listMaterials({ includeArchived: effectiveIncludeArchived }),
  });

  const archiveMutation = useMutation({
    mutationFn: archiveMaterial,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(true) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.materials.list(false) });
    },
  });

  function open(material: TrainingMaterialView, download = false) {
    setOpenError(null);
    openOrDownload(material, download).catch(setOpenError);
  }

  return (
    <Card data-slot="materials-list">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        {canManage ? (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={includeArchived}
              onChange={(event) => setIncludeArchived(event.target.checked)}
            />
            {t('materialsShowArchived')}
          </label>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {materialsQuery.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(materialsQuery.error)}
          </p>
        ) : null}
        {openError ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(openError)}
          </p>
        ) : null}
        {materialsQuery.data && materialsQuery.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('materialsEmpty')}</p>
        ) : null}
        <ul className="flex flex-col gap-2">
          {(materialsQuery.data?.items ?? []).map((material) => (
            <li
              key={material.material_id}
              className="flex items-center justify-between gap-2 rounded-md border border-border p-2"
              data-slot="material-row"
            >
              <div>
                <p className="text-sm font-medium">{material.title_ru}</p>
                <p className="text-xs text-muted-foreground">
                  {material.file_name}
                  {material.archived_at ? ` · ${t('materialsArchivedBadge')}` : ''}
                </p>
              </div>
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="outline" onClick={() => open(material)}>
                  {material.content_type === 'application/pdf' ? t('materialsOpenButton') : t('materialsDownloadButton')}
                </Button>
                {material.content_type === 'application/pdf' ? (
                  <Button type="button" size="sm" variant="outline" onClick={() => open(material, true)}>
                    {t('materialsDownloadButton')}
                  </Button>
                ) : null}
                {canManage && !material.archived_at ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => archiveMutation.mutate(material.material_id)}
                    disabled={archiveMutation.isPending}
                  >
                    {t('materialsArchiveButton')}
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
        {archiveMutation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {problemText(archiveMutation.error)}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
