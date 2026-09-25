import { describe, expect, it } from 'vitest';
import { flaggedTextQualityItems, textQualityFieldLabelRu, textQualityFlaggedCount } from './format';
import { ru } from '@/shared/i18n/ru';
import type { TextQualityFieldView, TextQualityReportView, TextQualitySource } from '@/shared/api';

function field(overrides: Partial<TextQualityFieldView> & { source: TextQualitySource }): TextQualityFieldView {
  return { text: 'sample text', misspellings: [], street: null, ...overrides };
}

function report(overrides: Partial<TextQualityReportView> = {}): TextQualityReportView {
  return { available: true, fields: [], dictionary_sha256: 'd', street_list_sha256: 's', unavailable_message_ru: null, ...overrides };
}

// I4 E35 (71 §71.12, D35): display only — everything flagged, or the reason nothing is, comes
// from the server; this suite pins the client-side grouping (one row per word/street) and the
// exhaustive source-label table, not the checking itself (backend's own suite covers that).
describe('text-quality display helpers', () => {
  it('names every TextQualitySource with its own ru.ts label', () => {
    const sources: TextQualitySource[] = [
      'ADDRESS_STREET',
      'DESCRIPTION_TEXT',
      'RECIPIENTS_COMMENT',
      'DDS_STATUS_COMMENT',
      'DDS_CARD_ISSUE_COMMENT',
      'DDS_CLOSE_COMMENT',
    ];
    const labels = sources.map(textQualityFieldLabelRu);
    expect(new Set(labels).size).toBe(sources.length); // every source has its own, distinct label
    expect(textQualityFieldLabelRu('ADDRESS_STREET')).toBe(ru.textQualitySourceAddressStreet);
  });

  it('flags nothing for an unavailable report, regardless of its fields', () => {
    const unavailable = report({
      available: false,
      unavailable_message_ru: ru.textQualitySectionTitle, // any non-null string; content is the caller's concern
      fields: [field({ source: 'ADDRESS_STREET', misspellings: [{ start: 0, end: 4, word: 'oops', suggestions: [] }] })],
    });
    expect(flaggedTextQualityItems(unavailable)).toEqual([]);
    expect(textQualityFlaggedCount(unavailable)).toBeNull();
  });

  it('flags nothing when available and every field is clean', () => {
    const clean = report({
      fields: [
        field({ source: 'DESCRIPTION_TEXT' }),
        field({ source: 'ADDRESS_STREET', street: { status: 'KNOWN', suggestions: [] } }),
      ],
    });
    expect(flaggedTextQualityItems(clean)).toEqual([]);
    expect(textQualityFlaggedCount(clean)).toBe(0);
  });

  it('one row per misspelled word, with its suggestion when the checker has one', () => {
    const withMisspellings = report({
      fields: [
        field({
          source: 'RECIPIENTS_COMMENT',
          misspellings: [
            { start: 0, end: 5, word: 'wordo', suggestions: ['word', 'wordy'] },
            { start: 6, end: 11, word: 'typoo', suggestions: [] },
          ],
        }),
      ],
    });
    const items = flaggedTextQualityItems(withMisspellings);
    expect(items).toHaveLength(2);
    expect(items[0]?.fieldLabel).toBe(ru.textQualitySourceRecipientsComment);
    expect(items[0]?.message).toContain('wordo');
    expect(items[0]?.message).toContain(ru.textQualityMisspelledLabel);
    expect(items[0]?.message).toContain('word'); // the first suggestion
    expect(items[1]?.message).toContain('typoo');
    expect(items[1]?.message).not.toContain(ru.textQualitySuggestionLabel); // no suggestion offered
  });

  it('flags a NEAR street with its suggestions and an UNKNOWN one without, never a KNOWN one', () => {
    const near = report({ fields: [field({ source: 'ADDRESS_STREET', street: { status: 'NEAR', suggestions: ['Correct Street'] } })] });
    const [nearItem] = flaggedTextQualityItems(near);
    expect(nearItem?.message).toContain(ru.textQualityStreetNearLabel);
    expect(nearItem?.message).toContain('Correct Street');

    const unknown = report({ fields: [field({ source: 'ADDRESS_STREET', street: { status: 'UNKNOWN', suggestions: [] } })] });
    expect(flaggedTextQualityItems(unknown)).toEqual([{ key: 'ADDRESS_STREET-street', fieldLabel: ru.textQualitySourceAddressStreet, message: ru.textQualityStreetUnknownLabel }]);

    const known = report({ fields: [field({ source: 'ADDRESS_STREET', street: { status: 'KNOWN', suggestions: [] } })] });
    expect(flaggedTextQualityItems(known)).toEqual([]);
  });

  it('counts every flagged word and street together', () => {
    const mixed = report({
      fields: [
        field({ source: 'DESCRIPTION_TEXT', misspellings: [{ start: 0, end: 4, word: 'oops', suggestions: [] }] }),
        field({ source: 'ADDRESS_STREET', street: { status: 'UNKNOWN', suggestions: [] } }),
      ],
    });
    expect(textQualityFlaggedCount(mixed)).toBe(2);
    expect(textQualityFlaggedCount(null)).toBeNull();
    expect(textQualityFlaggedCount(undefined)).toBeNull();
  });
});
