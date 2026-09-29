// Route: /instructor/scenarios (I4 E32, HLD `71-i4-wave4.md` §71.9, ТЗ ¶222, ¶229). The «Сценарии»
// upload page: a file input drives `validateScenarioFile` → `importScenarioVersion`, the pair
// `openapi.yaml` already exposed with no UI (`routers/scenarios.py:115-160`). The document's
// content is read client-side; `format` comes from the file extension (`.yaml`/`.yml` → YAML,
// `.json` → JSON) — "Edit" means uploading a new version, because versions are immutable (D4).
// Archive/unarchive (ТЗ ¶229, «удалять неактуальные сценарии») lists every scenario beside it.
// I7 E53: the list filters by «Категория событий» (G13), each scenario's versions can be downloaded
// as YAML/JSON (G14a — download → edit → upload as the next version), and validation issues read
// in Russian by rule number (G19, `scenario-issue-ru.ts`).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AppShell } from '@/shared/ui/app-shell';
import { Card, CardContent, CardHeader } from '@/shared/ui/card';
import { Button } from '@/shared/ui/button';
import { Badge } from '@/shared/ui/badge';
import { t } from '@/shared/i18n';
import { Hint } from '@/shared/ui/tour';
import { ru } from '@/shared/i18n/ru';
import { useAuthStore } from '@/entities/session';
import {
  archiveScenario,
  getScenarioVersionDocument,
  importScenarioVersion,
  listScenarioPage,
  listScenarioVersions,
  problemMessageRu,
  queryKeys,
  unarchiveScenario,
  validateScenarioFile,
  type ProblemCode,
  type ScenarioDocumentFormat,
  type ScenarioSummary,
  type ScenarioValidationReport,
  type ScenarioVersionListItem,
  type UserRole,
} from '@/shared/api';
import { ProblemError } from '@/shared/lib/api';
import { saveBlob } from '@/shared/lib/download';
import { CategoryChips } from './category-chips';
import { categoryOptionsOf, matchesCategories } from './scenario-categories';
import { scenarioIssueMessageRu } from './scenario-issue-ru';

const USER_ROLE_LABEL_KEY: Record<UserRole, keyof typeof ru> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

function formatOfFileName(name: string): 'YAML' | 'JSON' | null {
  const lower = name.toLowerCase();
  if (lower.endsWith('.yaml') || lower.endsWith('.yml')) return 'YAML';
  if (lower.endsWith('.json')) return 'JSON';
  return null;
}

function readFileText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function UploadCard() {
  const [content, setContent] = useState<string | null>(null);
  const [format, setFormat] = useState<'YAML' | 'JSON' | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [report, setReport] = useState<ScenarioValidationReport | null>(null);
  const [importedRu, setImportedRu] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  async function handleFile(file: File | null): Promise<void> {
    setReport(null);
    setImportedRu(null);
    setError(null);
    if (!file) {
      setContent(null);
      setFormat(null);
      setFileName(null);
      return;
    }
    setFileName(file.name);
    setFormat(formatOfFileName(file.name));
    setContent(await readFileText(file));
  }

  const validate = useMutation({
    mutationFn: () => validateScenarioFile({ format: format ?? 'YAML', content: content ?? '', source_path: fileName ?? undefined }),
    onSuccess: (result) => {
      setReport(result);
      setImportedRu(null);
    },
    onError: (err: unknown) => {
      setError(err instanceof ProblemError ? problemMessageRu(err.code as ProblemCode) : t('problemUnknown'));
    },
  });

  const doImport = useMutation({
    mutationFn: () => importScenarioVersion({ format: format ?? 'YAML', content: content ?? '', source_path: fileName ?? undefined }),
    onSuccess: async () => {
      setImportedRu(t('scenarioUploadImportedRu'));
      await queryClient.invalidateQueries({ queryKey: queryKeys.scenarioPicker.all() });
    },
    onError: (err: unknown) => {
      setError(err instanceof ProblemError ? problemMessageRu(err.code as ProblemCode) : t('problemUnknown'));
    },
  });

  const hasFile = content !== null && format !== null;

  return (
    <Card data-tour="scenario-upload">
      <CardHeader>
        <h2 className="font-heading text-base leading-snug font-medium">{t('scenarioUploadTitle')}</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          {t('scenarioUploadFieldLabel')}
          <input
            type="file"
            accept=".yaml,.yml,.json"
            onChange={(event) => void handleFile(event.target.files?.[0] ?? null)}
          />
        </label>
        {content !== null && format === null ? <p className="text-xs text-destructive">{t('scenarioUploadNoFile')}</p> : null}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasFile || validate.isPending}
            onClick={() => validate.mutate()}
          >
            {validate.isPending ? t('scenarioUploadValidating') : t('scenarioUploadValidateButton')}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!hasFile || doImport.isPending}
            onClick={() => doImport.mutate()}
          >
            {doImport.isPending ? t('scenarioUploadImporting') : t('scenarioUploadImportButton')}
          </Button>
          <Hint text={t('hintScenarioFile')} />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {importedRu ? <p className="text-sm text-emerald-600">{importedRu}</p> : null}
        {report ? (
          <div className="rounded-md border border-border p-2 text-sm">
            <p className={report.valid ? 'text-emerald-600' : 'text-destructive'}>
              {report.valid ? t('scenarioUploadValidRu') : t('scenarioUploadInvalidRu')}
            </p>
            {report.issues.length > 0 ? (
              <ul className="mt-1 flex flex-col gap-1">
                {report.issues.map((issue, index) => (
                  <li key={index} className="text-xs text-muted-foreground" title={issue.message}>
                    R{issue.rule_number} · {issue.location} — {scenarioIssueMessageRu(issue)}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ArchiveAction({ scenario }: { scenario: ScenarioSummary }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => (scenario.archived_at ? unarchiveScenario(scenario.scenario_id) : archiveScenario(scenario.scenario_id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.scenarioPicker.all() });
    },
  });

  return (
    <Button type="button" variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
      {scenario.archived_at ? t('scenarioUnarchiveButton') : t('scenarioArchiveButton')}
    </Button>
  );
}

function VersionDownloads({ version, slug }: { version: ScenarioVersionListItem; slug: string }) {
  const [failed, setFailed] = useState(false);
  const download = useMutation({
    mutationFn: async (format: ScenarioDocumentFormat) => {
      saveBlob(await getScenarioVersionDocument(version.id, format), `${slug}-v${version.version}.${format}`);
    },
    onMutate: () => setFailed(false),
    onError: () => setFailed(true),
  });

  return (
    <li className="flex flex-wrap items-center gap-2 text-xs">
      <span>
        {t('scenarioVersionLabel')} {version.version}
      </span>
      <Button type="button" variant="outline" size="sm" disabled={download.isPending} onClick={() => download.mutate('yaml')}>
        {t('scenarioDownloadButton')}
      </Button>
      <Button type="button" variant="ghost" size="sm" disabled={download.isPending} onClick={() => download.mutate('json')}>
        {t('scenarioDownloadJsonButton')}
      </Button>
      {failed ? (
        <span role="alert" className="text-destructive">
          {t('scenarioDownloadFailed')}
        </span>
      ) : null}
    </li>
  );
}

function ScenarioVersions({ scenario }: { scenario: ScenarioSummary }) {
  const versionsQuery = useQuery({
    queryKey: queryKeys.scenarios.versions(scenario.scenario_id),
    queryFn: () => listScenarioVersions(scenario.scenario_id),
  });
  return (
    <ul className="flex flex-col gap-1 pl-2">
      {(versionsQuery.data?.items ?? []).map((version) => (
        <VersionDownloads key={version.id} version={version} slug={scenario.slug} />
      ))}
    </ul>
  );
}

function ScenarioRow({ scenario }: { scenario: ScenarioSummary }) {
  const [showVersions, setShowVersions] = useState(false);
  return (
    <div className="flex flex-col gap-1 border-b border-border pb-2 last:border-0">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{scenario.title_ru}</span>
          <Badge variant="secondary">{scenario.category?.name_ru ?? t('scenarioCategoryNone')}</Badge>
          {scenario.archived_at ? <Badge variant="outline">{t('scenarioArchivedBadge')}</Badge> : null}
        </div>
        <div className="flex items-center gap-1">
          <Button type="button" variant="ghost" size="sm" aria-expanded={showVersions} onClick={() => setShowVersions((value) => !value)}>
            {showVersions ? t('scenarioVersionsHide') : t('scenarioVersionsButton')}
          </Button>
          <ArchiveAction scenario={scenario} />
        </div>
      </div>
      {showVersions ? <ScenarioVersions scenario={scenario} /> : null}
    </div>
  );
}

function ScenarioListCard() {
  const [showArchived, setShowArchived] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<number[]>([]);
  const scenariosQuery = useQuery({
    queryKey: queryKeys.scenarioPicker.list(showArchived),
    queryFn: () => listScenarioPage({ limit: 200, includeArchived: showArchived }),
  });
  const scenarios = scenariosQuery.data?.items ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
          {t('scenarioShowArchivedLabel')}
        </label>
        <CategoryChips options={categoryOptionsOf(scenarios)} selected={categoryFilter} onChange={setCategoryFilter} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {scenarios
          .filter((scenario) => matchesCategories(scenario, categoryFilter))
          .map((scenario) => (
            <ScenarioRow key={scenario.scenario_id} scenario={scenario} />
          ))}
      </CardContent>
    </Card>
  );
}

export function ScenariosPage() {
  const user = useAuthStore((state) => state.user);
  return (
    <AppShell title={t('scenarioUploadTitle')} userLabel={user?.display_name_ru} role={user ? t(USER_ROLE_LABEL_KEY[user.user_role]) : undefined}>
      <h1 className="text-lg font-semibold tracking-tight">{t('scenarioUploadTitle')}</h1>
      <div className="mt-4 flex flex-col gap-4">
        <UploadCard />
        <ScenarioListCard />
      </div>
    </AppShell>
  );
}
