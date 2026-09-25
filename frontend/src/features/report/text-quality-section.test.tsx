import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TextQualitySection } from './text-quality-section';
import { ru } from '@/shared/i18n/ru';
import { makeTextQualityReport } from './test-fixtures';

const UNAVAILABLE_STUB = 'UNAVAILABLE_STUB_MESSAGE';

// I4 E35 (71 §71.12, D35): the section renders exactly one of three states — never "0 errors"
// stood in for "the checker did not run" (SPEC §27's honesty rule).
describe('TextQualitySection', () => {
  it('renders the server-provided message verbatim when available is false', () => {
    render(
      <TextQualitySection
        textQuality={makeTextQualityReport({
          available: false,
          dictionary_sha256: null,
          street_list_sha256: null,
          unavailable_message_ru: UNAVAILABLE_STUB,
          fields: [{ source: 'ADDRESS_STREET', text: 'street value', misspellings: [{ start: 0, end: 4, word: 'oops', suggestions: [] }], street: null }],
        })}
      />,
    );
    expect(screen.getByText(UNAVAILABLE_STUB)).toBeInTheDocument();
    expect(screen.queryByText(ru.textQualityNoneFlagged)).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(ru.textQualityMisspelledLabel))).not.toBeInTheDocument();
  });

  it('renders the "nothing flagged" message when available and no field is flagged', () => {
    render(
      <TextQualitySection
        textQuality={makeTextQualityReport({
          fields: [
            { source: 'DESCRIPTION_TEXT', text: 'clean text', misspellings: [], street: null },
            { source: 'ADDRESS_STREET', text: 'known street', misspellings: [], street: { status: 'KNOWN', suggestions: [] } },
          ],
        })}
      />,
    );
    expect(screen.getByText(ru.textQualityNoneFlagged)).toBeInTheDocument();
  });

  it('lists a flagged word and a flagged street with their status when available', () => {
    render(
      <TextQualitySection
        textQuality={makeTextQualityReport({
          fields: [
            { source: 'RECIPIENTS_COMMENT', text: 'a comment', misspellings: [{ start: 0, end: 5, word: 'wordo', suggestions: ['wordy'] }], street: null },
            { source: 'ADDRESS_STREET', text: 'a street', misspellings: [], street: { status: 'NEAR', suggestions: ['Correct Street'] } },
          ],
        })}
      />,
    );
    expect(screen.queryByText(ru.textQualityNoneFlagged)).not.toBeInTheDocument();
    expect(screen.getByText(ru.textQualitySourceRecipientsComment)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`wordo.*${ru.textQualityMisspelledLabel}`))).toBeInTheDocument();
    expect(screen.getByText(ru.textQualitySourceAddressStreet)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`${ru.textQualityStreetNearLabel}.*Correct Street`))).toBeInTheDocument();
  });
});
