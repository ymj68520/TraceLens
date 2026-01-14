import { useSelector } from 'react-redux';
import en from '../locales/en';
import zh from '../locales/zh';

const locales = {
    en,
    zh,
};

export const useTranslation = () => {
    const { language } = useSelector((state) => state.settings);

    const t = (key) => {
        const currentLocale = locales[language] || locales.en;
        return currentLocale[key] || key;
    };

    return { t, language };
};

export default useTranslation;
