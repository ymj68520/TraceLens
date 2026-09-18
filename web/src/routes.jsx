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
import Investigation from './pages/Investigation/Investigation';
import InvestigationGraphRedirect from './pages/InvestigationGraphRedirect';
import FinalReportViewer from './pages/Investigation/FinalReportViewer';
import LegacyReportRedirect, { TaskReportRedirect, CaseReportRedirect } from './pages/LegacyReportRedirect';
import {
  WeChatForensicsRedirect, QQForensicsRedirect, WeChatGraphRedirect,
} from './pages/IMForensicsRedirect';
import OSS from './pages/OSS';
import Login from './pages/Login';
import Terminal from './pages/Terminal';
import Distributed from './pages/Distributed';
import FeatureGate from './components/common/FeatureGate';

const IMForensics = React.lazy(() => import('./pages/IMForensics/IMForensics'));

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
        // MVP (mvp-phase1-acceptance §4.3): combined-case module is gated off;
        // the route stays registered so deep links render a notice.
        path: 'cases',
        element: (
          <FeatureGate flag="combined_case_enabled">
            <Cases />
          </FeatureGate>
        ),
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
        // MVP (mvp-phase1-acceptance §4.6): memory forensics is trimmed;
        // the route stays registered so deep links render a notice.
        path: 'memory',
        element: (
          <FeatureGate flag="memory_forensics_enabled">
            <Memory />
          </FeatureGate>
        ),
      },
      {
        path: 'im-forensics',
        element: (
          <React.Suspense fallback={<div className="flex items-center justify-center h-full"><div className="text-slate-400">Loading...</div></div>}>
            <IMForensics />
          </React.Suspense>
        ),
      },
      {
        // 微信取证 / QQ 取证 / 微信关系分析 已合并为 /im-forensics（IMForensicsRedirect）
        path: 'wechat-forensics',
        element: <WeChatForensicsRedirect />,
      },
      {
        path: 'qq-forensics',
        element: <QQForensicsRedirect />,
      },
      {
        path: 'wechat-graph',
        element: <WeChatGraphRedirect />,
      },
      {
        // MVP (mvp-phase1-acceptance §4.7): OSS analysis is trimmed;
        // the route stays registered so deep links render a notice.
        path: 'oss',
        element: (
          <FeatureGate flag="oss_analysis_enabled">
            <OSS />
          </FeatureGate>
        ),
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
        // MVP (mvp-phase1-acceptance §4.3): gated with combined-case module.
        path: 'analysis-center',
        element: (
          <FeatureGate flag="combined_case_enabled">
            <AnalysisCenter />
          </FeatureGate>
        ),
      },
      {
        path: 'investigation',
        element: <Investigation />,
      },
      {
        path: 'investigation-graph',
        element: <InvestigationGraphRedirect />,
      },
      {
        path: 'investigation/report',
        element: <FinalReportViewer />,
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
