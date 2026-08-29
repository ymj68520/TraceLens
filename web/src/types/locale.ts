/**
 * Locale dictionaries. Keys are dot-namespaced; `useTranslation` does a
 * plain lookup and falls back to the key itself when a string is missing.
 */
export type LocaleKey = string;
export type LocaleDict = Record<LocaleKey, string>;
export type Language = 'zh' | 'en';
