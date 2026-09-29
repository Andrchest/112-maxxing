// I7 E43 (Q-E15-3): the «было → стало» list of one audit row, in Russian. The server sends each
// change as `{field: "<entity>.<field>[qualifier]?", before, after}` (`AuditChangeView`); this
// module turns the field into a Russian label and each value into Russian text. Both values
// `null` is a secret («изменён») — the server never sends a password, hash or token.
import { t, type I18nKey } from '@/shared/i18n';
import { LESSON_STATE_LABEL_KEY } from '@/features/lesson/lesson-labels';
import { SERVICE_RESPONSE_STATUS_LABEL_KEY } from '@/features/dds/dds-labels';
import type { AuditChangeView, SessionMode, SessionState, UserRole } from '@/shared/api';

const FIELD_LABEL_KEY: Record<string, I18nKey> = {
  'user.username': 'adminAuditFieldUserUsername',
  'user.display_name_ru': 'adminAuditFieldUserDisplayName',
  'user.user_role': 'adminAuditFieldUserRole',
  'user.is_active': 'adminAuditFieldUserIsActive',
  'user.password': 'adminAuditFieldUserPassword',
  'lesson.title_ru': 'adminAuditFieldLessonTitle',
  'lesson.session_mode': 'adminAuditFieldLessonSessionMode',
  'lesson.group_id': 'adminAuditFieldLessonGroup',
  'lesson.participants': 'adminAuditFieldLessonParticipants',
  'lesson.scenario_plan': 'adminAuditFieldLessonScenarioPlan',
  'lesson.timers': 'adminAuditFieldLessonTimers',
  'lesson.time_scale': 'adminAuditFieldLessonTimeScale',
  'lesson.pass_criteria': 'adminAuditFieldLessonPassCriteria',
  'lesson.state': 'adminAuditFieldLessonState',
  'lesson.aborted_cards': 'adminAuditFieldLessonAbortedCards',
  'lesson.report_released': 'adminAuditFieldLessonReportReleased',
  'lesson.released_cards': 'adminAuditFieldLessonReleasedCards',
  'lesson.weight': 'adminAuditFieldLessonWeight',
  'group.name_ru': 'adminAuditFieldGroupName',
  'group.members': 'adminAuditFieldGroupMembers',
  'scenario.slug': 'adminAuditFieldScenarioSlug',
  'scenario.archived': 'adminAuditFieldScenarioArchived',
  'scenario_version.title': 'adminAuditFieldScenarioVersionTitle',
  'scenario_version.version': 'adminAuditFieldScenarioVersionNumber',
  'scenario_version.content_sha256': 'adminAuditFieldScenarioVersionDigest',
  'material.title_ru': 'adminAuditFieldMaterialTitle',
  'material.file_name': 'adminAuditFieldMaterialFileName',
  'material.content_type': 'adminAuditFieldMaterialContentType',
  'material.size_bytes': 'adminAuditFieldMaterialSize',
  'material.archived': 'adminAuditFieldMaterialArchived',
  'comment.text': 'adminAuditFieldCommentText',
  'report.released': 'adminAuditFieldReportReleased',
  'score.total_points': 'adminAuditFieldScoreTotal',
  'score.rule_points': 'adminAuditFieldScoreRulePoints',
  'session.state': 'adminAuditFieldSessionState',
  'dds_leg.response_status': 'adminAuditFieldDdsLegStatus',
};

const ROLE_LABEL_KEY: Record<UserRole, I18nKey> = {
  TRAINEE: 'userRoleTrainee',
  INSTRUCTOR: 'userRoleInstructor',
  ADMIN: 'userRoleAdmin',
};

const SESSION_MODE_LABEL_KEY: Record<SessionMode, I18nKey> = {
  SINGLE_ROLE: 'instructorSessionModeSingleRole',
  FULL_CYCLE_SINGLE_TRAINEE: 'instructorSessionModeFullCycle',
  MULTI_TRAINEE: 'instructorSessionModeMultiTrainee',
  ASSESSMENT: 'instructorSessionModeAssessment',
};

const SESSION_STATE_LABEL_KEY: Record<SessionState, I18nKey> = {
  CREATED: 'sessionStateCreated',
  READY: 'sessionStateReady',
  ACTIVE: 'sessionStateActive',
  ROLE_TRANSITION: 'sessionStateRoleTransition',
  COMPLETED: 'sessionStateCompleted',
  ABORTED: 'sessionStateAborted',
};

// The enum-valued fields whose values have a Russian label elsewhere in the UI.
const VALUE_LABEL_KEYS: Record<string, Record<string, I18nKey>> = {
  'user.user_role': ROLE_LABEL_KEY,
  'lesson.session_mode': SESSION_MODE_LABEL_KEY,
  'lesson.state': LESSON_STATE_LABEL_KEY,
  'session.state': SESSION_STATE_LABEL_KEY,
  'dds_leg.response_status': SERVICE_RESPONSE_STATUS_LABEL_KEY,
};

const QUALIFIED = /^([^[]+)\[(.+)\]$/;

/** `"lesson.weight[2]"` → `{ name: "lesson.weight", qualifier: "2" }`. */
function splitField(field: string): { name: string; qualifier: string | null } {
  const match = QUALIFIED.exec(field);
  return match ? { name: match[1] ?? field, qualifier: match[2] ?? null } : { name: field, qualifier: null };
}

/** The Russian label of a change's field; an unknown field shows as sent. */
export function auditFieldLabelRu(field: string): string {
  const { name, qualifier } = splitField(field);
  const key = FIELD_LABEL_KEY[name];
  const label = key ? t(key) : name;
  if (qualifier === null) return label;
  return /^\d+$/.test(qualifier) ? `${label} (${t('adminAuditChangeCardNumber')}${qualifier})` : `${label} (${qualifier})`;
}

/** One value in Russian: `null` a dash, a boolean «да»/«нет», a known enum its label, a list or
 * object compact JSON. */
export function auditValueRu(field: string, value: unknown): string {
  if (value === null || value === undefined) return t('adminAuditChangeNone');
  if (typeof value === 'boolean') return value ? t('adminAuditChangeYes') : t('adminAuditChangeNo');
  if (typeof value === 'string') {
    const labels = VALUE_LABEL_KEYS[splitField(field).name];
    const key = labels?.[value];
    return key ? t(key) : value;
  }
  if (typeof value === 'number') return String(value).replace('.', ',');
  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) return value.join(', ');
  return JSON.stringify(value);
}

/** «поле: было → стало», or «поле: изменён» for a secret (both values `null`). */
export function auditChangeLineRu(change: AuditChangeView): string {
  const label = auditFieldLabelRu(change.field);
  if (change.before === null && change.after === null) return `${label}: ${t('adminAuditChangeSecret')}`;
  return `${label}: ${auditValueRu(change.field, change.before)} → ${auditValueRu(change.field, change.after)}`;
}
