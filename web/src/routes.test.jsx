import { matchRoutes } from 'react-router-dom';
import { expect, test, vi } from 'vitest';

vi.mock('./pages/CaseIntelligence', () => ({
  default: function CaseIntelligence() { return null; },
}));

import CaseIntelligence from './pages/CaseIntelligence';
import LegacyReportRedirect from './pages/LegacyReportRedirect';
import { appRoutes } from './routes';

test('exposes report migration routes without replacing the legacy redirect', () => {
  const childRoutes = appRoutes.find((route) => route.path === '/').children;
  const legacyRoute = childRoutes.find((route) => route.path === 'case-report');
  const intelligenceRoute = childRoutes.find((route) => route.path === 'case-intelligence');

  expect(legacyRoute.element.type).toBe(LegacyReportRedirect);
  expect(intelligenceRoute.element.type).toBe(CaseIntelligence);
  expect(matchRoutes(appRoutes, '/case-intelligence?taskId=t1')).not.toBeNull();
});
