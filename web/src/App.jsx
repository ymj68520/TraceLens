import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import Layout from './components/Layout/Layout';
import ErrorBoundary from './components/common/ErrorBoundary';
import { FIELD_AUTH_ENABLED, LOCAL_AUTO_SESSION_ENABLED } from './config/runtime';
import { getFieldToken } from './services/fieldSession';

function App() {
  const { theme } = useSelector((state) => state.settings);
  const location = useLocation();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  if (FIELD_AUTH_ENABLED && !getFieldToken()) return <Navigate to="/login" replace
    state={LOCAL_AUTO_SESSION_ENABLED ? { returnTo: location.pathname + location.search + location.hash } : undefined} />;

  return (
    <ErrorBoundary>
      <Layout>
        {LOCAL_AUTO_SESSION_ENABLED && <span className="sr-only">本机免登录调试模式，操作身份为本机调试操作员。</span>}
        <Outlet />
      </Layout>
    </ErrorBoundary>
  );
}

export default App;
