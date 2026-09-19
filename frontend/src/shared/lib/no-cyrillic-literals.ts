const CYRILLIC = /[Ѐ-ӿ]/;

const STRING_OR_TEMPLATE = /'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g;
const JSX_TEXT = />([^<>{}]+)</g;

/**
 * Finds Cyrillic string/template literals and Cyrillic JSX text nodes in a
 * .ts/.tsx source string. Enforces D12: every trainee-facing Russian string
 * lives in `src/shared/i18n/ru.ts` and reaches a component only through the
 * `t()` helper — never hard-coded inline.
 */
export function findCyrillicLiterals(source: string): string[] {
  const hits: string[] = [];

  for (const match of source.matchAll(STRING_OR_TEMPLATE)) {
    if (CYRILLIC.test(match[0])) {
      hits.push(match[0]);
    }
  }

  for (const match of source.matchAll(JSX_TEXT)) {
    const text = (match[1] ?? '').trim();
    if (text.length > 0 && CYRILLIC.test(text)) {
      hits.push(text);
    }
  }

  return hits;
}
