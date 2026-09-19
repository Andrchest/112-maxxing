import { describe, expect, it } from 'vitest';
import { findCyrillicLiterals } from './no-cyrillic-literals';

describe('findCyrillicLiterals', () => {
  it('flags a sabotaged inline Cyrillic string literal', () => {
    const sabotaged = `export function Bad() {\n  const title = "Оператор 112";\n  return <h1>{title}</h1>;\n}`;
    expect(findCyrillicLiterals(sabotaged)).toContain('"Оператор 112"');
  });

  it('flags a sabotaged inline Cyrillic JSX text node', () => {
    const sabotaged = `export function Bad() {\n  return <h1>Оператор 112</h1>;\n}`;
    expect(findCyrillicLiterals(sabotaged).some((hit) => hit.includes('Оператор'))).toBe(true);
  });

  it('passes clean source that only references i18n keys', () => {
    const clean = `import { t } from '@/shared/i18n';\nexport function Good() {\n  return <h1>{t('operatorTitle')}</h1>;\n}`;
    expect(findCyrillicLiterals(clean)).toEqual([]);
  });
});
