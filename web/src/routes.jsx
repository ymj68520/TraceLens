import React from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import App from './App';
import Dashboard from './pages/Dashboard';
import Tasks from './pages/Tasks';
import Cases from './pages/Cases';
import Timeline from './pages/Timeline';
import Files from './pages/Files';
import Android from './pages/Android';
import Memory from './pages/Memory';
import Search from './pages/Search';
import Statistics from './pages/Statistics';
import Settings from './pages/Settings';
import KnowledgeGraph from './pages/KnowledgeGraph';
import CaseIntelligence from './pages/CaseIntelligence';
import AnalysisCenter from './pages/AnalysisCenter';
import LegacyReportRedirect, { TaskReportRedirect, CaseReportRedirect } from './pages/LegacyReportRedirect';
import OSS from './pages/OSS';
import Login from './pages/Login';
import Terminal from './pages/Terminal';
import Distributed from './pages/Distributed';

const WeChatGraph = React.lazy(() => import('./pages/WeChatGraph/WeChatGraph'));

export const appRoutes = [
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
        path: 'memory',
        element: <Memory />,
      },
      {
        path: 'wechat-graph',
        element: (
          <React.Suspense fallback={<div className="flex items-center justify-center h-full"><div className="text-slate-400">Loading...</div></div>}>
            <WeChatGraph />
          </React.Suspense>
        ),
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
        path: 'case-intelligence',
        element: <CaseIntelligence />,
      },
      {
        path: 'analysis-center',
        element: <AnalysisCenter />,
      },
      {
        path: 'reports/task/:taskId',
        element: <TaskReportRedirect />,
      },
      {
        path: 'reports/case/:caseId',
        element: <CaseReportRedirect />,
      },
      {
        path: 'case-report',
        element: <LegacyReportRedirect />,
      },
      {
        path: 'terminal',
        element: <Terminal />,
      },
      {
        path: 'distributed',
        element: <Distributed />,
      },
    ],
  },
];

const router = createBrowserRouter(appRoutes);
export default router;
