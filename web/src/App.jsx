import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { Outlet } from 'react-router-dom';
import Layout from './components/Layout/Layout';
import ErrorBoundary from './components/common/ErrorBoundary';

function App() {
  const { theme } = useSelector((state) => state.settings);

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  return (
    <ErrorBoundary>
      <Layout>
        <Outlet />
      </Layout>
    </ErrorBoundary>
  );
}

export default App;
