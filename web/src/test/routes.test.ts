import { describe, it, expect } from 'vitest';
import { appRoutes } from '../routes';

function collectPaths(routes: unknown[]): string[] {
  const out: string[] = [];
  for (const r of routes as { path?: string; children?: unknown[] }[]) {
    if (r.path) out.push(r.path);
    if (r.children) out.push(...collectPaths(r.children));
  }
  return out;
}

describe('routes', () => {
  it('exposes the full page set', () => {
    const paths = collectPaths(appRoutes);
    for (const expected of [
      '/login',
      '/',
      'dashboard',
      'tasks',
      'cases',
      'timeline',
      'files',
      'android',
      'memory',
      'wechat-graph',
      'oss',
      'search',
      'statistics',
      'settings',
      'knowledge-graph',
      'case-intelligence',
      'analysis-center',
      'investigation',
      'terminal',
      'distributed',
    ]) {
      expect(paths).toContain(expected);
    }
  });

  it('keeps legacy report redirects', () => {
    const paths = collectPaths(appRoutes);
    expect(paths).toContain('reports/task/:taskId');
    expect(paths).toContain('reports/case/:caseId');
    expect(paths).toContain('case-report');
  });
});
