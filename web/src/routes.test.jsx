import { matchRoutes } from 'react-router-dom';
import { expect, test, vi } from 'vitest';

vi.mock('./pages/CaseIntelligence', () => ({
  default: function CaseIntelligence() { return null; },
}));
vi.mock('./pages/AnalysisCenter', () => ({
  default: function AnalysisCenter() { return null; },
}));
vi.mock('./pages/Investigation/Investigation', () => ({
  default: function Investigation() { return null; },
}));
vi.mock('./pages/Investigation/FinalReportViewer', () => ({
  default: function FinalReportViewer() { return null; },
}));

import CaseIntelligence from './pages/CaseIntelligence';
import AnalysisCenter from './pages/AnalysisCenter';
import Investigation from './pages/Investigation/Investigation';
import FinalReportViewer from './pages/Investigation/FinalReportViewer';
import LegacyReportRedirect, { TaskReportRedirect, CaseReportRedirect } from './pages/LegacyReportRedirect';
import { appRoutes } from './routes';

test('exposes report migration routes without replacing the legacy redirect', () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const legacyRoute = childRoutes.find((route) => route.path === 'case-report');
  const intelligenceRoute = childRoutes.find((route) => route.path === 'case-intelligence');
  const analysisRoute = childRoutes.find((route) => route.path === 'analysis-center');
  const investigationRoute = childRoutes.find((route) => route.path === 'investigation');
  const finalReportRoute = childRoutes.find((route) => route.path === 'investigation/report');

  expect(legacyRoute.element.type).toBe(LegacyReportRedirect);
  expect(intelligenceRoute.element.type).toBe(CaseIntelligence);
  expect(analysisRoute.element.type).toBe(AnalysisCenter);
  expect(investigationRoute.element.type).toBe(Investigation);
  expect(finalReportRoute.element.type).toBe(FinalReportViewer);
  expect(matchRoutes(appRoutes, '/case-intelligence?taskId=t1')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/analysis-center?task_id=t1')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/investigation?task_id=t1')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/investigation/report?task_id=t1')).not.toBeNull();
});

test('redirects legacy report routes to the intelligence page', () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const taskRoute = childRoutes.find((route) => route.path === 'reports/task/:taskId');
  const caseRoute = childRoutes.find((route) => route.path === 'reports/case/:caseId');

  expect(taskRoute.element.type).toBe(TaskReportRedirect);
  expect(caseRoute.element.type).toBe(CaseReportRedirect);
});

