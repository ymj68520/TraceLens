import { useAppSelector } from '../store';
import zh from '../locales/zh';
import en from '../locales/en';
import type { Language, LocaleDict } from '../types/locale';

const locales: Record<Language, LocaleDict> = { zh, en };

export const useTranslation = () => {
  const language = useAppSelector((state) => state.settings.language);

  const t = (key: string): string => {
    const dict = locales[language] || locales.en;
    return dict[key] ?? key;
  };

  return { t, language };
};

export default useTranslation;
