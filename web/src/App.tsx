import { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { useAppSelector } from './store';
import Layout from './components/layout/Layout';
import ErrorBoundary from './components/ui/ErrorBoundary';

export default function App() {
  const theme = useAppSelector((state) => state.settings.theme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return (
    <ErrorBoundary>
      <Layout>
        <Outlet />
      </Layout>
    </ErrorBoundary>
  );
}
