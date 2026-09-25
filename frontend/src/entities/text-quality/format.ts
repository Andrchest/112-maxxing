// I4 E35 (71 §71.12, D35): the display helpers `features/report`'s session-report section and
// `features/lesson`'s report table share (an entity, so neither feature imports the other — the
// same split `entities/statistics` uses for I4 E33). Exhaustive `TextQualitySource -> ru.ts key`
// table, so `tsc` fails the moment `schema.d.ts` grows a source this file does not name. Display
// only: every word, street and sha256 is the server's own (D11); nothing is re-checked here.
import { ru } from '@/shared/i18n/ru';
import { t } from '@/shared/i18n';
import type { TextQualityFieldView, TextQualityReportView, TextQualitySource } from '@/shared/api';

const TEXT_QUALITY_SOURCE_LABEL_KEY: Record<TextQualitySource, keyof typeof ru> = {
  ADDRESS_STREET: 'textQualitySourceAddressStreet',
  DESCRIPTION_TEXT: 'textQualitySourceDescriptionText',
  RECIPIENTS_COMMENT: 'textQualitySourceRecipientsComment',
  DDS_STATUS_COMMENT: 'textQualitySourceDdsStatusComment',
  DDS_CARD_ISSUE_COMMENT: 'textQualitySourceDdsCardIssueComment',
  DDS_CLOSE_COMMENT: 'textQualitySourceDdsCloseComment',
};

export function textQualityFieldLabelRu(source: TextQualitySource): string {
  return t(TEXT_QUALITY_SOURCE_LABEL_KEY[source]);
}

/** One row the section lists: a field's label beside one flagged word or street lookup. Nothing
 * is listed for a field with no misspellings and a `KNOWN` (or absent) street — «Замечаний нет»
 * covers that case instead of an empty list (SPEC §27's honesty rule, mirrored on the client). */
export interface FlaggedTextQualityItem {
  key: string;
  fieldLabel: string;
  message: string;
}

function misspellingItems(field: TextQualityFieldView): FlaggedTextQualityItem[] {
  const fieldLabel = textQualityFieldLabelRu(field.source);
  return field.misspellings.map((span, index) => {
    const suggestion = span.suggestions[0];
    const base = `«${span.word}» — ${t('textQualityMisspelledLabel')}`;
    return {
      key: `${field.source}-word-${index}-${span.start}`,
      fieldLabel,
      message: suggestion ? `${base} (${t('textQualitySuggestionLabel')}: ${suggestion})` : base,
    };
  });
}

function streetItem(field: TextQualityFieldView): FlaggedTextQualityItem | null {
  if (!field.street || field.street.status === 'KNOWN') return null;
  const fieldLabel = textQualityFieldLabelRu(field.source);
  const message =
    field.street.status === 'NEAR'
      ? `${t('textQualityStreetNearLabel')}: ${field.street.suggestions.join(', ')}`
      : t('textQualityStreetUnknownLabel');
  return { key: `${field.source}-street`, fieldLabel, message };
}

/** Every flagged word/street of an `available` report, in field order. `[]` for
 * `available: false` (the caller renders `unavailable_message_ru` instead) and for a report with
 * nothing to flag (the caller renders «Замечаний нет» instead). */
export function flaggedTextQualityItems(report: TextQualityReportView): FlaggedTextQualityItem[] {
  if (!report.available) return [];
  const items: FlaggedTextQualityItem[] = [];
  for (const field of report.fields) {
    items.push(...misspellingItems(field));
    const street = streetItem(field);
    if (street) items.push(street);
  }
  return items;
}

/** The lesson report table's «Грамотность» column: the flagged-item count, or `null` when the
 * card has no `text_quality` at all (an unscored card) or the checker was unavailable for it. */
export function textQualityFlaggedCount(report: TextQualityReportView | null | undefined): number | null {
  if (!report || !report.available) return null;
  return flaggedTextQualityItems(report).length;
}
