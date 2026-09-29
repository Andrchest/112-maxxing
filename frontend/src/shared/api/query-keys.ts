// Central TanStack Query key factories (D12). One canonical shape per resource so every
// feature invalidates and prefetches the same cache entry instead of hand-rolling arrays.
export const queryKeys = {
  auth: {
    me: () => ['auth', 'me'] as const,
  },
  users: {
    list: (role?: string) => ['users', 'list', role ?? 'ALL'] as const,
  },
  health: {
    ready: () => ['health', 'ready'] as const,
  },
  // -- I3 E2a: the reference pack (70 §70.6) --------------------------------------------------
  reference: {
    services: (pack?: string) => ['reference', 'services', pack ?? 'default'] as const,
  },
  scenarios: {
    list: () => ['scenarios'] as const,
    versions: (scenarioId: string) => ['scenarios', scenarioId, 'versions'] as const,
    // I3 E4b (manager follow-up): the trainee-safe summary, keyed by version id directly (the
    // lesson plan only carries `scenario_version_id`, not its parent scenario's id).
    versionSummary: (scenarioVersionId: string) => ['scenarios', 'version-summary', scenarioVersionId] as const,
  },
  sessions: {
    list: (scope: 'MINE' | 'ALL' = 'MINE') => ['sessions', 'list', scope] as const,
    detail: (sessionId: string) => ['sessions', sessionId] as const,
    snapshot: (sessionId: string) => ['sessions', sessionId, 'snapshot'] as const,
    // I3 E0 (D10): the operator transcript's history hydration (`listSessionEvents`).
    transcript: (sessionId: string) => ['sessions', sessionId, 'transcript'] as const,
  },
  // -- E10: the DDS console's own REST reads (openapi.yaml; D12) ------------------------------
  dds: {
    workItem: (sessionId: string) => ['dds', sessionId, 'work-item'] as const,
    resources: (sessionId: string) => ['dds', sessionId, 'resources'] as const,
    notifications: (sessionId: string) => ['dds', sessionId, 'notifications'] as const,
    radioMessages: (sessionId: string) => ['dds', sessionId, 'radio-messages'] as const,
    // I3 E5c: the memo's per-service legs list (`listDdsLegs`) — one cache entry per session,
    // shared by every component that reads or invalidates it.
    legs: (sessionId: string) => ['dds', sessionId, 'legs'] as const,
    // I3 E6b: the ДДС phone line (`listDdsCalls`), refreshed on every `DDS_CALL_*` event.
    calls: (sessionId: string) => ['dds', sessionId, 'calls'] as const,
  },
  // -- E16: post-session report and replay (SPEC §29; openapi `reports` tag) ------------------
  reports: {
    detail: (sessionId: string) => ['reports', sessionId] as const,
    explanation: (sessionId: string) => ['reports', sessionId, 'explanation'] as const,
    inferenceMetrics: (sessionId: string) => ['reports', sessionId, 'inference-metrics'] as const,
    // I4 E32: instructor comments on a session result (71 §71.9).
    comments: (sessionId: string) => ['reports', sessionId, 'comments'] as const,
  },
  // -- E17-C: instructor live overview (openapi `instructor` tag, R4) ------------------------
  instructor: {
    overview: (sessionId: string) => ['instructor', sessionId, 'overview'] as const,
  },
  // -- I3 E4b: lessons and the cross-session incident list (70 §70.3.6) -----------------------
  lessons: {
    list: (scope: 'MINE' | 'ALL' = 'ALL') => ['lessons', 'list', scope] as const,
    detail: (lessonId: string) => ['lessons', lessonId] as const,
    report: (lessonId: string) => ['lessons', lessonId, 'report'] as const,
    // I4 E32: instructor comments on a lesson result (71 §71.9).
    comments: (lessonId: string) => ['lessons', lessonId, 'comments'] as const,
  },
  incidents: {
    list: (roleType?: string, q?: string) => ['incidents', 'list', roleType ?? 'ANY', q ?? ''] as const,
  },
  // -- I3 E9a: trainee groups and difficulty-weight proposals (70 §70.3.7) --------------------
  traineeGroups: {
    list: () => ['trainee-groups', 'list'] as const,
  },
  weightProposals: {
    detail: (lessonId: string) => ['lessons', lessonId, 'weight-proposals'] as const,
  },
  scenarioPicker: {
    /** Prefix of every scenario list below — invalidate this after archive/unarchive/upload. */
    all: () => ['scenarios', 'picker'] as const,
    /** The checkbox «Показывать архивные» is part of the key, so toggling it refetches. */
    list: (includeArchived = false) => ['scenarios', 'picker', includeArchived] as const,
  },
  // -- I4 E34: methodical materials, «Справочная база» (HLD 71 §71.11) ------------------------
  materials: {
    list: (includeArchived: boolean) => ['materials', 'list', includeArchived] as const,
  },
  // -- I4 E33: per-trainee statistics and the trainee's own history (71 §71.10) ---------------
  statistics: {
    list: (groupId?: string, from?: string, to?: string) =>
      ['statistics', 'list', groupId ?? 'ALL', from ?? '', to ?? ''] as const,
    myHistory: () => ['statistics', 'my-history'] as const,
    // I5 E36, Q-E12-2: the trainee rating, same filters as `list`.
    rating: (groupId?: string, from?: string, to?: string) =>
      ['statistics', 'rating', groupId ?? 'ALL', from ?? '', to ?? ''] as const,
  },
  // -- I4 E30: Admin UI (71 §71.7) — E28's accounts and E29's monitoring reads ----------------
  admin: {
    users: (role?: string, includeInactive?: boolean) =>
      ['admin', 'users', role ?? 'ALL', includeInactive ?? false] as const,
    auditLog: (userId?: string, action?: string, from?: string, to?: string, offset = 0, withChanges = false) =>
      ['admin', 'audit-log', userId ?? '', action ?? '', from ?? '', to ?? '', offset, withChanges] as const,
    usageStats: (from?: string, to?: string) => ['admin', 'usage-stats', from ?? '', to ?? ''] as const,
    serverLoad: () => ['admin', 'server-load'] as const,
    errors: (from?: string, to?: string) => ['admin', 'errors', from ?? '', to ?? ''] as const,
    alerts: () => ['admin', 'alerts'] as const,
    backupStatus: () => ['admin', 'backup-status'] as const,
  },
} as const;
