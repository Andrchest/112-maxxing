import { ru } from './ru';

export type I18nKey = keyof typeof ru;

/** Typed lookup into the Russian string bundle. The only sanctioned source
 * of trainee-facing UI text — never hard-code a string in a component. */
export function t(key: I18nKey): string {
  return ru[key];
}
