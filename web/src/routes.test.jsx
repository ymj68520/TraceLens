import { MemoryRouter, matchRoutes, useLocation } from 'react-router-dom';
import { expect, test, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';

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
import {
  WeChatForensicsRedirect, QQForensicsRedirect, WeChatGraphRedirect,
} from './pages/IMForensicsRedirect';
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
  // MVP (mvp-phase1-acceptance §4.3): the analysis-center page is mounted
  // behind a FeatureGate; the route itself must stay registered.
  expect(analysisRoute.element.type.displayName || analysisRoute.element.type.name).toBe('FeatureGate');
  expect(analysisRoute.element.props.children.type).toBe(AnalysisCenter);
  // MVP (mvp-phase1-acceptance §4.6/§4.7): memory forensics and OSS analysis
  // are trimmed behind their feature gates the same way.
  const memoryRoute = childRoutes.find((route) => route.path === 'memory');
  const ossRoute = childRoutes.find((route) => route.path === 'oss');
  expect(memoryRoute.element.type.name).toBe('FeatureGate');
  expect(memoryRoute.element.props.flag).toBe('memory_forensics_enabled');
  expect(memoryRoute.element.props.children.type.name).toBe('Memory');
  expect(ossRoute.element.type.name).toBe('FeatureGate');
  expect(ossRoute.element.props.flag).toBe('oss_analysis_enabled');
  expect(ossRoute.element.props.children.type.name).toBe('OSS');
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

test('merged investigation-graph route redirects to the workbench with task context', async () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const graphRoute = childRoutes.find((route) => route.path === 'investigation-graph');

  let location;
  function Probe() {
    location = useLocation();
    return null;
  }
  render(
    <MemoryRouter initialEntries={['/investigation-graph?task_id=t1']}>
      {graphRoute.element}
      <Probe />
    </MemoryRouter>,
  );

  await waitFor(() => expect(location.pathname).toBe('/investigation'));
  expect(location.search).toContain('task_id=t1');
});

test('merged im-forensics routes keep the legacy paths redirecting', async () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const wechatRoute = childRoutes.find((route) => route.path === 'wechat-forensics');
  const qqRoute = childRoutes.find((route) => route.path === 'qq-forensics');
  const graphRoute = childRoutes.find((route) => route.path === 'wechat-graph');

  expect(wechatRoute.element.type).toBe(WeChatForensicsRedirect);
  expect(qqRoute.element.type).toBe(QQForensicsRedirect);
  expect(graphRoute.element.type).toBe(WeChatGraphRedirect);
  expect(matchRoutes(appRoutes, '/im-forensics')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/wechat-forensics')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/qq-forensics')).not.toBeNull();
  expect(matchRoutes(appRoutes, '/wechat-graph?task_id=t1')).not.toBeNull();

  let location;
  function Probe() {
    location = useLocation();
    return null;
  }

  const { unmount } = render(
    <MemoryRouter initialEntries={['/wechat-forensics']}>
      {wechatRoute.element}
      <Probe />
    </MemoryRouter>,
  );
  await waitFor(() => expect(location.pathname).toBe('/im-forensics'));
  expect(location.search).toBe('?platform=wechat');
  unmount();

  render(
    <MemoryRouter initialEntries={['/qq-forensics']}>
      {qqRoute.element}
      <Probe />
    </MemoryRouter>,
  );
  await waitFor(() => expect(location.pathname).toBe('/im-forensics'));
  expect(location.search).toBe('?platform=qq');
  unmount();

  // wx_/qq_ 前缀映射为平台 + 导入选择，原始 task_id 透传为图谱数据源覆盖
  render(
    <MemoryRouter initialEntries={['/wechat-graph?task_id=wx_imp-1']}>
      {graphRoute.element}
      <Probe />
    </MemoryRouter>,
  );
  await waitFor(() => expect(location.pathname).toBe('/im-forensics'));
  expect(location.search).toBe('?platform=wechat&import_id=imp-1&tab=graph');
  unmount();

  render(
    <MemoryRouter initialEntries={['/wechat-graph?task_id=task-9']}>
      {graphRoute.element}
      <Probe />
    </MemoryRouter>,
  );
  await waitFor(() => expect(location.pathname).toBe('/im-forensics'));
  expect(location.search).toContain('tab=graph');
  expect(location.search).toContain('task_id=task-9');
});

