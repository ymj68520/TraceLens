import { useEffect } from 'react';
import { useSelector } from 'react-redux';

/**
 * ThemeProvider component that applies the theme class to the document root
 * based on the current theme setting in Redux store.
 */
const ThemeProvider = ({ children }) => {
    const theme = useSelector((state) => state.settings.theme);

    useEffect(() => {
        // Apply theme class to document root
        const root = document.documentElement;

        if (theme === 'dark') {
            root.classList.add('dark');
            root.style.colorScheme = 'dark';
        } else {
            root.classList.remove('dark');
            root.style.colorScheme = 'light';
        }
    }, [theme]);

    return children;
};

export default ThemeProvider;
