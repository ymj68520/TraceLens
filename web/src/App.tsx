import { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { useAppSelector } from './store';
import Layout from './components/layout/Layout';
import ErrorBoundary from './components/ui/ErrorBoundary';
import PageErrorBoundary from './components/common/PageErrorBoundary';

export default function App() {
  const theme = useAppSelector((state) => state.settings.theme);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return (
    <ErrorBoundary>
      <Layout>
        <PageErrorBoundary>
          <Outlet />
        </PageErrorBoundary>
      </Layout>
    </ErrorBoundary>
  );
}
