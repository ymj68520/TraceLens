import { createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';
import Dashboard from './pages/Dashboard';
import Tasks from './pages/Tasks';
import Cases from './pages/Cases';
import Timeline from './pages/Timeline';
import Files from './pages/Files';
import Android from './pages/Android';
import Search from './pages/Search';
import Statistics from './pages/Statistics';
import Settings from './pages/Settings';
import KnowledgeGraph from './pages/KnowledgeGraph';
import CaseIntelligence from './pages/CaseIntelligence';
import OSS from './pages/OSS';
import Login from './pages/Login';
import Terminal from './pages/Terminal';

const router = createBrowserRouter([
  {
    path: '/login',
    element: <Login />,
  },
  {
    path: '/',
    element: <App />,
    children: [
      {
        index: true,
        element: <Navigate to="/dashboard" replace />,
      },
      {
        path: 'dashboard',
        element: <Dashboard />,
      },
      {
        path: 'tasks',
        element: <Tasks />,
      },
      {
        path: 'cases',
        element: <Cases />,
      },
      {
        path: 'timeline',
        element: <Timeline />,
      },
      {
        path: 'files',
        element: <Files />,
      },
      {
        path: 'android',
        element: <Android />,
      },
      {
        path: 'oss',
        element: <OSS />,
      },
      {
        path: 'search',
        element: <Search />,
      },
      {
        path: 'statistics',
        element: <Statistics />,
      },
      {
        path: 'settings',
        element: <Settings />,
      },
      {
        path: 'knowledge-graph',
        element: <KnowledgeGraph />,
      },
      {
        path: 'case-report',
        element: <CaseIntelligence />,
      },
      {
        path: 'terminal',
        element: <Terminal />,
      },
    ],
  },
]);
export default router;
