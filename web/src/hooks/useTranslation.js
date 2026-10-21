import zh from '../locales/zh';

export const useTranslation = () => {
    const t = (key) => {
        return zh[key] || key;
    };

    return { t, language: 'zh' };
};

export default useTranslation;
