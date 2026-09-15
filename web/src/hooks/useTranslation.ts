import { useAppSelector } from '../store';
import zh from '../locales/zh';
import en from '../locales/en';
import type { Language, LocaleDict } from '../types/locale';
import type { TranslationKey } from '../locales/keys';

const locales: Record<Language, LocaleDict> = { zh, en };

// Dev-only bookkeeping so a missing key warns exactly once instead of on
// every render (translation lookups run during render, sometimes in loops).
const warnedKeys = new Set<string>();

export const useTranslation = () => {
  const language = useAppSelector((state) => state.settings.language);

  // Known keys type-check and autocomplete; `& Record<never, never>` keeps the
  // parameter wide (any string passes, e.g. dynamic template keys) without
  // tripping @typescript-eslint/ban-types.
  const t = (key: TranslationKey | (string & Record<never, never>)): string => {
    const dict = locales[language] || locales.en;
    const value = dict[key];
    if (value === undefined && import.meta.env.DEV && !warnedKeys.has(key)) {
      warnedKeys.add(key);
      console.warn(`[i18n] missing translation key: "${key}" (language: ${language})`);
    }
    return value ?? key;
  };

  return { t, language };
};

export default useTranslation;
