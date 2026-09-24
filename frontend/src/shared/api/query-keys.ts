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
  },
  // -- E16: post-session report and replay (SPEC §29; openapi `reports` tag) ------------------
  reports: {
    detail: (sessionId: string) => ['reports', sessionId] as const,
    explanation: (sessionId: string) => ['reports', sessionId, 'explanation'] as const,
    inferenceMetrics: (sessionId: string) => ['reports', sessionId, 'inference-metrics'] as const,
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
  },
  incidents: {
    list: (roleType?: string, q?: string) => ['incidents', 'list', roleType ?? 'ANY', q ?? ''] as const,
  },
} as const;
