import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { Navigate, Outlet } from 'react-router-dom';
import Layout from './components/Layout/Layout';
import ErrorBoundary from './components/common/ErrorBoundary';
import { FIELD_AUTH_ENABLED } from './config/runtime';
import { getFieldToken } from './services/fieldSession';

function App() {
  const { theme } = useSelector((state) => state.settings);

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  if (FIELD_AUTH_ENABLED && !getFieldToken()) return <Navigate to="/login" replace />;

  return (
    <ErrorBoundary>
      <Layout>
        <Outlet />
      </Layout>
    </ErrorBoundary>
  );
}

export default App;
