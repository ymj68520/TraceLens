import { Suspense, lazy, type ReactNode } from 'react';
import { createBrowserRouter, Navigate, useParams, useSearchParams } from 'react-router-dom';
import App from './App';
import Dashboard from './pages/Dashboard';
import Tasks from './pages/Tasks';
import Cases from './pages/Cases';
import Timeline from './pages/Timeline';
import Files from './pages/Files';
import Android from './pages/Android';
import Memory from './pages/Memory';
import SearchPage from './pages/SearchPage';
import Statistics from './pages/Statistics';
import Settings from './pages/Settings';
import KnowledgeGraph from './pages/KnowledgeGraph';
import CaseIntelligence from './pages/CaseIntelligence';
import AnalysisCenter from './pages/AnalysisCenter';
import Investigation from './pages/Investigation';
import OSS from './pages/OSS';
import Login from './pages/Login';
import Terminal from './pages/Terminal';
import Distributed from './pages/Distributed';
import NotFound from './pages/NotFound';
import { LoadingBlock } from './components/ui/Spinner';

const WeChatGraph = lazy(() => import('./pages/WeChatGraph'));

const Suspended = ({ children }: { children: ReactNode }) => (
  <Suspense fallback={<LoadingBlock />}>{children}</Suspense>
);

function LegacyReportRedirect() {
  const [searchParams] = useSearchParams();
  const caseId = searchParams.get('case_id');
  if (caseId) {
    return <Navigate to={`/case-intelligence?case_id=${encodeURIComponent(caseId)}`} replace />;
  }
  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  if (taskId) {
    return <Navigate to={`/case-intelligence?task_id=${encodeURIComponent(taskId)}`} replace />;
  }
  return <Navigate to="/tasks" replace />;
}

export function TaskReportRedirect() {
  const { taskId } = useParams();
  return <Navigate to={`/case-intelligence?task_id=${encodeURIComponent(taskId ?? '')}`} replace />;
}

export function CaseReportRedirect() {
  const { caseId } = useParams();
  return <Navigate to={`/case-intelligence?case_id=${encodeURIComponent(caseId ?? '')}`} replace />;
}

export const appRoutes = [
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: <Dashboard /> },
      { path: 'tasks', element: <Tasks /> },
      { path: 'cases', element: <Cases /> },
      { path: 'timeline', element: <Timeline /> },
      { path: 'files', element: <Files /> },
      { path: 'android', element: <Android /> },
      { path: 'memory', element: <Memory /> },
      {
        path: 'wechat-graph',
        element: (
          <Suspended>
            <WeChatGraph />
          </Suspended>
        ),
      },
      { path: 'oss', element: <OSS /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'statistics', element: <Statistics /> },
      { path: 'settings', element: <Settings /> },
      { path: 'knowledge-graph', element: <KnowledgeGraph /> },
      { path: 'case-intelligence', element: <CaseIntelligence /> },
      { path: 'analysis-center', element: <AnalysisCenter /> },
      { path: 'investigation', element: <Investigation /> },
      { path: 'reports/task/:taskId', element: <TaskReportRedirect /> },
      { path: 'reports/case/:caseId', element: <CaseReportRedirect /> },
      { path: 'case-report', element: <LegacyReportRedirect /> },
      { path: 'terminal', element: <Terminal /> },
      { path: 'distributed', element: <Distributed /> },
      { path: '*', element: <NotFound /> },
    ],
  },
];

const router = createBrowserRouter(appRoutes);
export default router;
