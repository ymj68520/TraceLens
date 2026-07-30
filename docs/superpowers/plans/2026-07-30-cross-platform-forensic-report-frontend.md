# Cross-Platform Forensic Report Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the online report workspace, shared data-source boundary, version lifecycle UI, directory/search/page navigation, responsive layout, and baseline renderers before platform-specific adapters arrive.

**Architecture:** A `ReportDataSource` interface isolates React components from transport. The online implementation calls `/api/reports`; a fixture implementation proves the same workspace can operate without HTTP and becomes the seam used by the offline bundle later. `ForensicReportPage` resolves task/case routes, owns version selection and generation polling, and renders a responsive shell composed from focused toolbar, directory, content, pagination, status, and renderer-registry components.

**Tech Stack:** React 18, React Router 6, Axios, Vite 5, Tailwind CSS, Vitest, jsdom, React Testing Library, user-event

## Global Constraints

- Reports contain both structured artifacts and the existing five-chapter AI analysis.
- Support both single-task (`task`) and multi-image case (`case`) scopes through one protocol.
- Deliver online browsing and offline HTML ZIP packages; PDF and DOCX are out of scope.
- Include every parsed artifact, not only evidence marked relevant to the case.
- Highlight deleted, recovered, high-risk, relevant, and analysis-referenced records.
- Published report versions are immutable; regeneration always creates a new monotonically increasing version.
- Sensitive values remain unmasked and are displayed verbatim.
- Offline packages include approved thumbnails and small previews only; large/original evidence remains a path-and-hash reference.
- Platforms and categories are emitted from actual non-empty data; never create empty Android, Windows, or Linux sections.
- One evidence item may contain multiple platforms.
- A non-critical adapter/category failure produces a ready report with warnings; manifest, shard-index, or publication failure fails the whole version.
- Existing `/api/llm/case-report/{task_id}` and `/api/llm/case-report-by-case/{case_id}` APIs remain available during migration.
- Online and offline renderers consume the same manifest, page, record, attachment, search-result, and analysis-reference shapes.
- The report tree and records must remain usable on narrow screens; wide tables scroll horizontally.
- The unrelated existing modification at `.superpowers/sdd/2026-07-29-miui-backup-forensics-phase1/final-remediation-round-report.md` must not be staged or committed.

## Consumed Backend Contract

Plan 1 must be complete. This plan consumes:

```javascript
POST /api/reports
GET  /api/reports?scope_type=<task|case>&scope_id=<id>
GET  /api/reports/:reportId/status
GET  /api/reports/:reportId/manifest
GET  /api/reports/:reportId/categories/:categoryId/pages/:page
GET  /api/reports/:reportId/search?q=<query>&offset=<n>&limit=<n>
```

The frontend data-source interface established here is:

```javascript
export class ReportDataSource {
  listVersions(scopeType, scopeId) {}
  createVersion(scopeType, scopeId) {}
  getStatus(reportId) {}
  getManifest(reportId) {}
  getCategoryPage(reportId, categoryId, page) {}
  search(reportId, query, { offset = 0, limit = 50 } = {}) {}
  getPreviewUrl(reportId, attachment) {}
  getOfflineBundleUrl(reportId) {}
}
```

---

### Task 1: Add a frontend test harness

**Files:**
- Modify: `web/package.json:5-43`
- Modify: `web/vite.config.js:4-58`
- Create: `web/src/test/setup.js`
- Create: `web/src/test/renderWithRouter.jsx`
- Create: `web/src/test/smoke.test.jsx`

**Interfaces:**
- Consumes: Vite React plugin and React Router.
- Produces: `npm test`, `npm run test:watch`, jest-dom matchers, browser cleanup, and `renderWithRouter(ui, { route })`.

- [ ] **Step 1: Add the intentionally failing smoke test**

```jsx
// web/src/test/smoke.test.jsx
import { screen } from '@testing-library/react';
import { renderWithRouter } from './renderWithRouter';

function Smoke() {
  return <h1>Report test harness</h1>;
}

test('renders React components in jsdom', () => {
  renderWithRouter(<Smoke />);
  expect(screen.getByRole('heading', { name: 'Report test harness' })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the missing test command**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/test/smoke.test.jsx
```

Expected: `npm ERR! Missing script: "test"`.

- [ ] **Step 3: Add exact testing dependencies and scripts**

Add these development dependencies using npm so `package-lock.json` is updated:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm install --save-dev vitest@^2.1.9 jsdom@^25.0.1 @testing-library/react@^16.1.0 @testing-library/jest-dom@^6.6.3 @testing-library/user-event@^14.5.2
```

Add scripts:

```json
"test": "vitest",
"test:watch": "vitest --watch"
```

Add Vite test configuration:

```javascript
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: './src/test/setup.js',
  css: true,
},
```

- [ ] **Step 4: Implement setup and router helper**

```javascript
// web/src/test/setup.js
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
```

```jsx
// web/src/test/renderWithRouter.jsx
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

export function renderWithRouter(ui, { route = '/' } = {}) {
  window.history.pushState({}, 'Test page', route);
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}
```

- [ ] **Step 5: Run the smoke test**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/test/smoke.test.jsx
```

Expected: one test passes.

- [ ] **Step 6: Commit the frontend test harness**

```bash
git add web/package.json web/package-lock.json web/vite.config.js web/src/test/setup.js web/src/test/renderWithRouter.jsx web/src/test/smoke.test.jsx
git commit -m "test(web): add report component harness"
```

---

### Task 2: Implement online and fixture report data sources

**Files:**
- Create: `web/src/services/reportDataSource.js`
- Create: `web/src/services/reportService.js`
- Test: `web/src/services/reportDataSource.test.js`
- Test: `web/src/services/reportService.test.js`

**Interfaces:**
- Consumes: `pythonApi` from `web/src/services/api.js` and the backend contract above.
- Produces: `ReportDataSource`, `HttpReportDataSource`, `FixtureReportDataSource`, singleton `reportDataSource`, and wrapper functions `listReportVersions`, `createReportVersion`, `getReportStatus`, `getReportManifest`, `getReportCategoryPage`, `searchReport`.

- [ ] **Step 1: Write failing data-source contract tests**

```javascript
// web/src/services/reportDataSource.test.js
import { FixtureReportDataSource } from './reportDataSource';

const fixture = {
  versions: [{ report_id: 'r1', version: 1, status: 'ready' }],
  manifests: { r1: { report_id: 'r1', title: 'Fixture', categories: [] } },
  pages: { 'r1:android.sms:1': { page: 1, records: [{ record_id: 'rec_1' }] } },
  searches: { 'r1:验证码': { total: 1, hits: [{ record_id: 'rec_1' }] } },
};

test('fixture and HTTP sources share the same asynchronous contract', async () => {
  const source = new FixtureReportDataSource(fixture);
  expect(await source.listVersions('task', 't1')).toEqual(fixture.versions);
  expect(await source.getManifest('r1')).toEqual(fixture.manifests.r1);
  expect(await source.getCategoryPage('r1', 'android.sms', 1)).toEqual(
    fixture.pages['r1:android.sms:1'],
  );
  expect((await source.search('r1', '验证码')).total).toBe(1);
});
```

```javascript
// web/src/services/reportService.test.js
import { beforeEach, expect, test, vi } from 'vitest';
import { pythonApi } from './api';
import { HttpReportDataSource } from './reportDataSource';

vi.mock('./api', () => ({ pythonApi: { get: vi.fn(), post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

test('HTTP source encodes category and search parameters', async () => {
  pythonApi.get.mockResolvedValue({ records: [] });
  const source = new HttpReportDataSource(pythonApi);
  await source.getCategoryPage('r1', 'android.wechat/messages', 2);
  await source.search('r1', '手机号 / hash', { offset: 4, limit: 20 });
  expect(pythonApi.get).toHaveBeenNthCalledWith(
    1,
    '/api/reports/r1/categories/android.wechat%2Fmessages/pages/2',
  );
  expect(pythonApi.get).toHaveBeenNthCalledWith(
    2,
    '/api/reports/r1/search',
    { params: { q: '手机号 / hash', offset: 4, limit: 20 } },
  );
});
```

- [ ] **Step 2: Run tests and confirm modules are missing**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/services/reportDataSource.test.js src/services/reportService.test.js
```

Expected: both suites fail to resolve `reportDataSource.js`.

- [ ] **Step 3: Implement the interface and two implementations**

```javascript
// web/src/services/reportDataSource.js
export class ReportDataSource {
  async listVersions() { throw new Error('not implemented'); }
  async createVersion() { throw new Error('not implemented'); }
  async getStatus() { throw new Error('not implemented'); }
  async getManifest() { throw new Error('not implemented'); }
  async getCategoryPage() { throw new Error('not implemented'); }
  async search() { throw new Error('not implemented'); }
  getPreviewUrl() { throw new Error('not implemented'); }
  getOfflineBundleUrl() { throw new Error('not implemented'); }
}

export class HttpReportDataSource extends ReportDataSource {
  constructor(client) {
    super();
    this.client = client;
  }

  listVersions(scopeType, scopeId) {
    return this.client.get('/api/reports', {
      params: { scope_type: scopeType, scope_id: scopeId },
    });
  }

  createVersion(scopeType, scopeId) {
    return this.client.post('/api/reports', {
      scope_type: scopeType,
      scope_id: scopeId,
    });
  }

  getStatus(reportId) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/status`);
  }

  getManifest(reportId) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/manifest`);
  }

  getCategoryPage(reportId, categoryId, page) {
    return this.client.get(
      `/api/reports/${encodeURIComponent(reportId)}/categories/${encodeURIComponent(categoryId)}/pages/${page}`,
    );
  }

  search(reportId, query, { offset = 0, limit = 50 } = {}) {
    return this.client.get(`/api/reports/${encodeURIComponent(reportId)}/search`, {
      params: { q: query, offset, limit },
    });
  }

  getPreviewUrl(reportId, attachment) {
    return attachment.preview_path
      ? `/api/reports/${encodeURIComponent(reportId)}/previews/${encodeURIComponent(attachment.attachment_id)}`
      : null;
  }

  getOfflineBundleUrl(reportId) {
    return `/api/reports/${encodeURIComponent(reportId)}/offline`;
  }
}

export class FixtureReportDataSource extends ReportDataSource {
  constructor(fixture) {
    super();
    this.fixture = fixture;
  }
  async listVersions() { return this.fixture.versions || []; }
  async createVersion() { throw new Error('fixture data source is read-only'); }
  async getStatus(reportId) {
    return (this.fixture.versions || []).find((item) => item.report_id === reportId) || null;
  }
  async getManifest(reportId) { return this.fixture.manifests[reportId]; }
  async getCategoryPage(reportId, categoryId, page) {
    return this.fixture.pages[`${reportId}:${categoryId}:${page}`];
  }
  async search(reportId, query) {
    return this.fixture.searches?.[`${reportId}:${query}`] || { total: 0, hits: [] };
  }
  getPreviewUrl(_reportId, attachment) { return attachment.preview_path || null; }
  getOfflineBundleUrl() { return null; }
}
```

```javascript
// web/src/services/reportService.js
import { pythonApi } from './api';
import { HttpReportDataSource } from './reportDataSource';

export const reportDataSource = new HttpReportDataSource(pythonApi);
export const listReportVersions = (...args) => reportDataSource.listVersions(...args);
export const createReportVersion = (...args) => reportDataSource.createVersion(...args);
export const getReportStatus = (...args) => reportDataSource.getStatus(...args);
export const getReportManifest = (...args) => reportDataSource.getManifest(...args);
export const getReportCategoryPage = (...args) => reportDataSource.getCategoryPage(...args);
export const searchReport = (...args) => reportDataSource.search(...args);
```

- [ ] **Step 4: Run data-source tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/services/reportDataSource.test.js src/services/reportService.test.js
```

Expected: both suites pass.

- [ ] **Step 5: Commit the data-source boundary**

```bash
git add web/src/services/reportDataSource.js web/src/services/reportService.js web/src/services/reportDataSource.test.js web/src/services/reportService.test.js
git commit -m "feat(web): add report data source boundary"
```

---

### Task 3: Add report routes, compatibility redirect, and context-aware navigation

**Files:**
- Create: `web/src/pages/ForensicReportPage.jsx`
- Create: `web/src/pages/LegacyReportRedirect.jsx`
- Modify: `web/src/routes.jsx:1-105`
- Modify: `web/src/components/tasks/TaskTable.jsx:47-68,139-143`
- Modify: `web/src/pages/Cases.jsx:330-339,373-390`
- Modify: `web/src/components/Layout/Layout.jsx:1-53,90-115,149-151`
- Test: `web/src/pages/LegacyReportRedirect.test.jsx`
- Test: `web/src/components/tasks/TaskTable.test.jsx`

**Interfaces:**
- Consumes: React Router `useParams`, `useSearchParams`, and `Navigate`.
- Produces: `/reports/task/:taskId`, `/reports/case/:caseId`, compatibility redirect from `/case-report`, and stable helper `getReportTarget(searchParams) -> string`.

- [ ] **Step 1: Write failing redirect and task-link tests**

```jsx
// web/src/pages/LegacyReportRedirect.test.jsx
import { Route, Routes } from 'react-router-dom';
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import LegacyReportRedirect from './LegacyReportRedirect';

function Destination() {
  return <div>new-report-route</div>;
}

test.each([
  ['/case-report?task_id=t1', '/reports/task/t1'],
  ['/case-report?taskId=t2', '/reports/task/t2'],
  ['/case-report?case_id=c1', '/reports/case/c1'],
])('redirects %s', (route, expected) => {
  renderWithRouter(
    <Routes>
      <Route path="/case-report" element={<LegacyReportRedirect />} />
      <Route path="/reports/task/:taskId" element={<Destination />} />
      <Route path="/reports/case/:caseId" element={<Destination />} />
    </Routes>,
    { route },
  );
  expect(screen.getByText('new-report-route')).toBeInTheDocument();
  expect(window.location.pathname).toBe(expected);
});
```

```jsx
// web/src/components/tasks/TaskTable.test.jsx
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../../test/renderWithRouter';
import TaskTable from './TaskTable';

test('completed task links to the versioned report workspace', () => {
  renderWithRouter(
    <TaskTable
      tasks={[{ id: 'task-1', status: 'completed', timestamps: {}, progress: {} }]}
      onCancel={() => {}} onDelete={() => {}} onJoinCase={() => {}}
    />,
  );
  expect(screen.getByRole('link', { name: 'Report' })).toHaveAttribute(
    'href', '/reports/task/task-1',
  );
});
```

- [ ] **Step 2: Run route tests and confirm failures**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/pages/LegacyReportRedirect.test.jsx src/components/tasks/TaskTable.test.jsx
```

Expected: missing component plus old `/case-report` link assertion failure.

- [ ] **Step 3: Implement the redirect and initial report page route resolver**

```jsx
// web/src/pages/LegacyReportRedirect.jsx
import { Navigate, useSearchParams } from 'react-router-dom';

export function getReportTarget(searchParams) {
  const caseId = searchParams.get('case_id');
  if (caseId) return `/reports/case/${encodeURIComponent(caseId)}`;
  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  if (taskId) return `/reports/task/${encodeURIComponent(taskId)}`;
  return '/tasks';
}

export default function LegacyReportRedirect() {
  const [searchParams] = useSearchParams();
  return <Navigate to={getReportTarget(searchParams)} replace />;
}
```

```jsx
// web/src/pages/ForensicReportPage.jsx
import { useParams } from 'react-router-dom';

export default function ForensicReportPage({ scopeType }) {
  const params = useParams();
  const scopeId = scopeType === 'case' ? params.caseId : params.taskId;
  return (
    <section aria-label="Forensic report">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">取证报告</h1>
      <p className="text-sm text-slate-500">{scopeType}: {scopeId}</p>
    </section>
  );
}
```

Add routes:

```jsx
{ path: 'reports/task/:taskId', element: <ForensicReportPage scopeType="task" /> },
{ path: 'reports/case/:caseId', element: <ForensicReportPage scopeType="case" /> },
{ path: 'case-report', element: <LegacyReportRedirect /> },
```

- [ ] **Step 4: Replace all report links and update sidebar behavior**

Use these exact replacements:

```jsx
// TaskTable
<Link to={`/reports/task/${task.id}`}>Report</Link>
<Link to={`/reports/case/${forensicCase.id}`}>...</Link>

// Cases
navigate(`/reports/case/${fc.id}`)
navigate(`/reports/task/${t.id}`)
```

In `Layout.jsx`, replace the old report navigation item with a `FileText` item whose target is computed from `currentTaskId`:

```jsx
{ name: t('nav.case_center'), href: currentTaskId ? `/reports/task/${currentTaskId}` : '/tasks', icon: FileText },
```

Update active matching so nested report routes are active:

```javascript
const isActive = (path) =>
  location.pathname === path || (path.startsWith('/reports/') && location.pathname.startsWith('/reports/'));
```

Remove `/case-report` from `taskContextPages`; the report href already contains its task ID.

- [ ] **Step 5: Run route/link tests and build**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/pages/LegacyReportRedirect.test.jsx src/components/tasks/TaskTable.test.jsx
npm run build
```

Expected: tests pass and Vite build completes.

- [ ] **Step 6: Commit routes and migration links**

```bash
git add web/src/pages/ForensicReportPage.jsx web/src/pages/LegacyReportRedirect.jsx web/src/routes.jsx web/src/components/tasks/TaskTable.jsx web/src/pages/Cases.jsx web/src/components/Layout/Layout.jsx web/src/pages/LegacyReportRedirect.test.jsx web/src/components/tasks/TaskTable.test.jsx
git commit -m "feat(web): route reports to dedicated workspace"
```

---

### Task 4: Build version history, generation polling, and report status states

**Files:**
- Create: `web/src/hooks/useReportVersion.js`
- Create: `web/src/components/reports/ReportStatusPanel.jsx`
- Create: `web/src/components/reports/VersionHistory.jsx`
- Create: `web/src/components/reports/ReportToolbar.jsx`
- Modify: `web/src/pages/ForensicReportPage.jsx`
- Test: `web/src/hooks/useReportVersion.test.jsx`
- Test: `web/src/components/reports/VersionHistory.test.jsx`

**Interfaces:**
- Consumes: `ReportDataSource` methods from Task 2.
- Produces: `useReportVersion({ scopeType, scopeId, dataSource, pollInterval })` returning `{ versions, selectedVersion, manifest, loading, error, generating, selectVersion, createVersion, refresh }`.

- [ ] **Step 1: Write failing hook tests for latest-ready selection and polling recovery**

```jsx
// web/src/hooks/useReportVersion.test.jsx
import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportVersion } from './useReportVersion';

const ready = { report_id: 'r1', version: 1, status: 'ready' };
const running = { report_id: 'r2', version: 2, status: 'generating', progress: 20 };

test('selects latest ready version and loads its manifest', async () => {
  const source = {
    listVersions: vi.fn().mockResolvedValue([running, ready]),
    getStatus: vi.fn(),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r1', title: 'Report' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  await waitFor(() => expect(result.current.manifest?.report_id).toBe('r1'));
  expect(result.current.selectedVersion.report_id).toBe('r1');
});

test('polls an existing generating version after refresh until it is ready', async () => {
  vi.useFakeTimers();
  const source = {
    listVersions: vi.fn().mockResolvedValue([running]),
    getStatus: vi.fn().mockResolvedValue({ ...running, status: 'ready', progress: 100 }),
    getManifest: vi.fn().mockResolvedValue({ report_id: 'r2' }),
  };
  const { result } = renderHook(() => useReportVersion({
    scopeType: 'task', scopeId: 't1', dataSource: source, pollInterval: 5,
  }));
  await act(async () => vi.advanceTimersByTimeAsync(10));
  await waitFor(() => expect(result.current.manifest?.report_id).toBe('r2'));
  vi.useRealTimers();
});
```

- [ ] **Step 2: Run hook test and verify the missing hook**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/hooks/useReportVersion.test.jsx
```

Expected: module resolution failure.

- [ ] **Step 3: Implement the version hook without losing generation on refresh**

```javascript
// web/src/hooks/useReportVersion.js
import { useCallback, useEffect, useRef, useState } from 'react';

export function useReportVersion({ scopeType, scopeId, dataSource, pollInterval = 2000 }) {
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const timerRef = useRef(null);

  const loadManifest = useCallback(async (version) => {
    if (!version || version.status !== 'ready') {
      setManifest(null);
      return;
    }
    setManifest(await dataSource.getManifest(version.report_id));
  }, [dataSource]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await dataSource.listVersions(scopeType, scopeId);
      setVersions(list);
      const current = selectedVersion
        ? list.find((item) => item.report_id === selectedVersion.report_id)
        : null;
      const next = current || list.find((item) => item.status === 'ready') || list[0] || null;
      setSelectedVersion(next);
      await loadManifest(next);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [dataSource, loadManifest, scopeId, scopeType, selectedVersion?.report_id]);

  useEffect(() => { refresh(); }, [scopeType, scopeId]);

  useEffect(() => {
    const generating = versions.find((item) => ['queued', 'generating'].includes(item.status));
    if (!generating) return undefined;
    const poll = async () => {
      const status = await dataSource.getStatus(generating.report_id);
      setVersions((items) => items.map((item) => item.report_id === status.report_id ? status : item));
      if (status.status === 'ready') {
        setSelectedVersion(status);
        await loadManifest(status);
      } else if (status.status !== 'failed') {
        timerRef.current = setTimeout(poll, pollInterval);
      }
    };
    timerRef.current = setTimeout(poll, pollInterval);
    return () => clearTimeout(timerRef.current);
  }, [versions.map((item) => `${item.report_id}:${item.status}`).join('|'), dataSource, loadManifest, pollInterval]);

  const selectVersion = useCallback(async (version) => {
    setSelectedVersion(version);
    await loadManifest(version);
  }, [loadManifest]);

  const createVersion = useCallback(async () => {
    const created = await dataSource.createVersion(scopeType, scopeId);
    setVersions((items) => [created, ...items]);
    setSelectedVersion(created);
    setManifest(null);
    return created;
  }, [dataSource, scopeId, scopeType]);

  return {
    versions, selectedVersion, manifest, loading, error,
    generating: versions.find((item) => ['queued', 'generating'].includes(item.status)) || null,
    selectVersion, createVersion, refresh,
  };
}
```

Ensure hook dependencies do not cause infinite list refreshes. If the exact expression above triggers repeated refresh in React strict mode, retain `selectedVersion` in a ref and keep the public return contract unchanged.

- [ ] **Step 4: Implement version/status presentation**

`ReportStatusPanel` must render these exact states based on props:

```jsx
// no versions
<div role="status">尚未生成报告</div>

// queued or generating
<div role="status">{version.stage} · {version.progress}%</div>

// failed
<div role="alert">报告生成失败：{version.error}</div>

// incompatible manifest
<div role="alert">当前报告模式不兼容，请生成新版本。</div>
```

`VersionHistory` renders radio buttons labelled `版本 {version}` and status text. `ReportToolbar` renders report title, version, generated time, platform badges, `生成新版本`, `导出离线 HTML`, and `版本历史` buttons; disable offline export until a URL is available in Plan 5.

Add a `VersionHistory.test.jsx` that clicks version 1 and asserts `onSelect(versionOne)`.

- [ ] **Step 5: Integrate the hook into `ForensicReportPage`**

Use an injectable prop for tests and default to `reportDataSource`:

```jsx
export default function ForensicReportPage({ scopeType, dataSource = reportDataSource }) {
  // resolve scopeId
  const state = useReportVersion({ scopeType, scopeId, dataSource });
  // render toolbar + status/history or manifest shell
}
```

If no versions exist, show the generate action. If a historical ready version is selected, keep it read-only while `生成新版本` creates a separate version.

- [ ] **Step 6: Run hook and component tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/hooks/useReportVersion.test.jsx src/components/reports/VersionHistory.test.jsx
```

Expected: all tests pass.

- [ ] **Step 7: Commit report lifecycle UI**

```bash
git add web/src/hooks/useReportVersion.js web/src/hooks/useReportVersion.test.jsx web/src/components/reports/ReportStatusPanel.jsx web/src/components/reports/VersionHistory.jsx web/src/components/reports/VersionHistory.test.jsx web/src/components/reports/ReportToolbar.jsx web/src/pages/ForensicReportPage.jsx
git commit -m "feat(web): manage report versions and status"
```

---

### Task 5: Build the responsive report shell, directory, search navigation, and pagination

**Files:**
- Create: `web/src/components/reports/ReportWorkspace.jsx`
- Create: `web/src/components/reports/ReportDirectory.jsx`
- Create: `web/src/components/reports/ReportSearch.jsx`
- Create: `web/src/components/reports/CategorySection.jsx`
- Create: `web/src/components/reports/CategoryPagination.jsx`
- Create: `web/src/hooks/useReportCategory.js`
- Create: `web/src/hooks/useReportSearch.js`
- Modify: `web/src/pages/ForensicReportPage.jsx`
- Test: `web/src/components/reports/ReportWorkspace.test.jsx`
- Test: `web/src/hooks/useReportCategory.test.jsx`
- Test: `web/src/hooks/useReportSearch.test.jsx`

**Interfaces:**
- Consumes: manifest `directory`, `categories`, data-source `getCategoryPage` and `search`.
- Produces: selected category/page state, search hit cursor, directory drawer state, and callbacks `selectCategory(categoryId, page = 1)` and `selectSearchHit(hit)`.

- [ ] **Step 1: Write failing category and search hook tests**

```jsx
// web/src/hooks/useReportCategory.test.jsx
import { renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportCategory } from './useReportCategory';

test('loads only the selected category page', async () => {
  const source = { getCategoryPage: vi.fn().mockResolvedValue({ page: 2, records: ['row'] }) };
  const { result } = renderHook(() => useReportCategory({
    dataSource: source, reportId: 'r1', categoryId: 'windows.event_logs', page: 2,
  }));
  await waitFor(() => expect(result.current.data?.records).toEqual(['row']));
  expect(source.getCategoryPage).toHaveBeenCalledWith('r1', 'windows.event_logs', 2);
});
```

```jsx
// web/src/hooks/useReportSearch.test.jsx
import { act, renderHook, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import { useReportSearch } from './useReportSearch';

test('supports next and previous hit navigation', async () => {
  const source = { search: vi.fn().mockResolvedValue({
    total: 2,
    hits: [
      { record_id: 'r1', category_id: 'android.sms', page: 1 },
      { record_id: 'r2', category_id: 'linux.shell', page: 3 },
    ],
  }) };
  const { result } = renderHook(() => useReportSearch({ dataSource: source, reportId: 'report' }));
  await act(async () => result.current.submit('root'));
  await waitFor(() => expect(result.current.currentHit.record_id).toBe('r1'));
  act(() => result.current.next());
  expect(result.current.currentHit.record_id).toBe('r2');
  act(() => result.current.previous());
  expect(result.current.currentHit.record_id).toBe('r1');
});
```

- [ ] **Step 2: Run tests and confirm missing hooks**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/hooks/useReportCategory.test.jsx src/hooks/useReportSearch.test.jsx
```

Expected: module resolution failures.

- [ ] **Step 3: Implement category and search hooks**

```javascript
// web/src/hooks/useReportCategory.js
import { useEffect, useState } from 'react';

export function useReportCategory({ dataSource, reportId, categoryId, page }) {
  const [state, setState] = useState({ data: null, loading: false, error: null });
  useEffect(() => {
    if (!reportId || !categoryId || !page) return undefined;
    let active = true;
    setState({ data: null, loading: true, error: null });
    dataSource.getCategoryPage(reportId, categoryId, page)
      .then((data) => active && setState({ data, loading: false, error: null }))
      .catch((error) => active && setState({ data: null, loading: false, error }));
    return () => { active = false; };
  }, [dataSource, reportId, categoryId, page]);
  return state;
}
```

```javascript
// web/src/hooks/useReportSearch.js
import { useMemo, useState } from 'react';

export function useReportSearch({ dataSource, reportId }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState({ total: 0, hits: [] });
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (nextQuery) => {
    setLoading(true);
    try {
      const next = await dataSource.search(reportId, nextQuery, { offset: 0, limit: 200 });
      setQuery(nextQuery);
      setResult(next);
      setCursor(0);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const hits = result.hits || [];
  const next = () => setCursor((value) => hits.length ? (value + 1) % hits.length : 0);
  const previous = () => setCursor((value) => hits.length ? (value - 1 + hits.length) % hits.length : 0);
  return {
    query, result, currentHit: hits[cursor] || null, cursor,
    loading, error, submit, next, previous,
  };
}
```

- [ ] **Step 4: Implement the directory, search controls, and pagination**

`ReportDirectory` recursively renders `manifest.directory`. Each leaf category button must expose:

```jsx
<button aria-label={`打开 ${node.title}`} onClick={() => onSelect(node.category_id, 1)}>
  <span>{node.title}</span>
  <span>{node.total}</span>
  {node.deleted > 0 && <span>已删除 {node.deleted}</span>}
  {node.high_risk > 0 && <span>高风险 {node.high_risk}</span>}
  {node.relevant > 0 && <span>重点 {node.relevant}</span>}
</button>
```

`ReportSearch` contains a search input, `查找`, `上一个`, and `下一个`; disable previous/next when no hits. `CategoryPagination` contains previous, next, page number input, and page-size display. A page change must call `onPageChange(page)` and must not reload the manifest.

- [ ] **Step 5: Implement the responsive shell**

```jsx
// web/src/components/reports/ReportWorkspace.jsx
import CategorySection from './CategorySection';
import ReportDirectory from './ReportDirectory';
import ReportSearch from './ReportSearch';

export default function ReportWorkspace({
  manifest, dataSource, reportId, selectedCategory, selectedPage,
  onSelectCategory, onSelectPage, searchState, directoryOpen, onDirectoryOpenChange,
}) {
  const category = manifest.categories.find(
    (item) => item.category_id === selectedCategory,
  ) || null;

  return (
    <div className="relative grid min-h-[70vh] grid-cols-1 gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
      <button
        type="button"
        className="lg:hidden"
        aria-expanded={directoryOpen}
        onClick={() => onDirectoryOpenChange(!directoryOpen)}
      >
        打开报告目录
      </button>
      <aside
        aria-label="报告目录"
        className={`${directoryOpen ? 'fixed inset-0 z-50 block bg-white p-4 dark:bg-slate-900' : 'hidden'} lg:sticky lg:top-20 lg:block lg:h-[calc(100vh-7rem)] lg:overflow-y-auto`}
      >
        <ReportSearch {...searchState} />
        <ReportDirectory
          directory={manifest.directory}
          onSelect={(categoryId, page) => {
            onSelectCategory(categoryId, page);
            onDirectoryOpenChange(false);
          }}
        />
      </aside>
      <main className="min-w-0 space-y-6" aria-label="报告正文">
        {category ? (
          <CategorySection
            reportId={reportId}
            category={category}
            page={selectedPage}
            dataSource={dataSource}
            onPageChange={onSelectPage}
          />
        ) : (
          <p>请选择报告目录中的分类。</p>
        )}
      </main>
    </div>
  );
}
```

Add a mobile `打开报告目录` button with `aria-expanded`. The workspace test must open the drawer, select a category, and assert only that page is requested.

- [ ] **Step 6: Connect search hits to category/page navigation**

When `currentHit` changes, call:

```javascript
if (hit?.category_id && hit?.page) {
  onSelectCategory(hit.category_id, hit.page);
}
```

After the page renders, add `data-record-id={record.record_id}` to every record wrapper and scroll the matching record into view. If the target is a section hit without a record ID, select the section without record scrolling.

- [ ] **Step 7: Run workspace tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/hooks/useReportCategory.test.jsx src/hooks/useReportSearch.test.jsx src/components/reports/ReportWorkspace.test.jsx
```

Expected: directory expansion, drawer, page navigation, and hit navigation tests pass.

- [ ] **Step 8: Commit report navigation**

```bash
git add web/src/components/reports/ReportWorkspace.jsx web/src/components/reports/ReportWorkspace.test.jsx web/src/components/reports/ReportDirectory.jsx web/src/components/reports/ReportSearch.jsx web/src/components/reports/CategorySection.jsx web/src/components/reports/CategoryPagination.jsx web/src/hooks/useReportCategory.js web/src/hooks/useReportCategory.test.jsx web/src/hooks/useReportSearch.js web/src/hooks/useReportSearch.test.jsx web/src/pages/ForensicReportPage.jsx
git commit -m "feat(web): browse report directory and pages"
```

---

### Task 6: Add the renderer registry and baseline structured presentation

**Files:**
- Create: `web/src/components/reports/renderers/registry.js`
- Create: `web/src/components/reports/renderers/GenericTableRenderer.jsx`
- Create: `web/src/components/reports/renderers/KeyValueRenderer.jsx`
- Create: `web/src/components/reports/renderers/RecordBadges.jsx`
- Create: `web/src/components/reports/renderers/AttachmentList.jsx`
- Modify: `web/src/components/reports/CategorySection.jsx`
- Test: `web/src/components/reports/renderers/registry.test.jsx`
- Test: `web/src/components/reports/renderers/GenericTableRenderer.test.jsx`

**Interfaces:**
- Consumes: page shard `records`, category `renderer`, and `ReportRecord` fields from Plan 1.
- Produces: `registerReportRenderer(name, component)`, `getReportRenderer(name)`, built-in `table` and `key_value` renderers, and uniform state/risk/relevance/reference badges.

- [ ] **Step 1: Write failing registry and badge tests**

```jsx
// web/src/components/reports/renderers/registry.test.jsx
import { getReportRenderer, registerReportRenderer } from './registry';

function Custom() { return null; }

test('returns generic table for unknown renderer and allows explicit registration', () => {
  expect(getReportRenderer('missing').displayName).toBe('GenericTableRenderer');
  registerReportRenderer('custom', Custom);
  expect(getReportRenderer('custom')).toBe(Custom);
});
```

```jsx
// web/src/components/reports/renderers/GenericTableRenderer.test.jsx
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../../../test/renderWithRouter';
import GenericTableRenderer from './GenericTableRenderer';

test('shows full sensitive text and uniform forensic badges', () => {
  renderWithRouter(<GenericTableRenderer records={[{
    record_id: 'rec_1', title: 'WiFi', data_state: 'deleted', severity: 'high',
    is_relevant: true, source_path: '/data/misc/wifi/WifiConfigStore.xml',
    source_table: 'wifi_networks', source_record_id: '7',
    fields: { pre_shared_key: 'CorrectHorseBatteryStaple' },
    hashes: {}, attachments: [], analysis_references: [{ chapter: '证据分析' }],
  }]} />);
  expect(screen.getByText('CorrectHorseBatteryStaple')).toBeInTheDocument();
  expect(screen.getByText('已删除')).toBeInTheDocument();
  expect(screen.getByText('高风险')).toBeInTheDocument();
  expect(screen.getByText('重点证据')).toBeInTheDocument();
  expect(screen.getByText('被 证据分析 引用')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run renderer tests and verify missing modules**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers/registry.test.jsx src/components/reports/renderers/GenericTableRenderer.test.jsx
```

Expected: module resolution failures.

- [ ] **Step 3: Implement registry and generic renderers**

```javascript
// web/src/components/reports/renderers/registry.js
import GenericTableRenderer from './GenericTableRenderer';
import KeyValueRenderer from './KeyValueRenderer';

const renderers = new Map([
  ['table', GenericTableRenderer],
  ['key_value', KeyValueRenderer],
]);

export function registerReportRenderer(name, component) {
  renderers.set(name, component);
}

export function getReportRenderer(name) {
  return renderers.get(name) || GenericTableRenderer;
}
```

`GenericTableRenderer` must:

- derive columns from the union of `fields` keys on the current page;
- render inside `overflow-x-auto`;
- show `title`, badges, source path/table/record ID, hashes, and attachments;
- retain complete field values in the DOM without masking;
- use `data-record-id` on each row.

`KeyValueRenderer` renders one bordered card per record and is used for device/system metadata categories.

`RecordBadges` exact label mapping:

```javascript
const stateLabels = { existing: '现存', deleted: '已删除', recovered: '已恢复', unknown: '未知' };
const severityLabels = { info: '信息', low: '低风险', medium: '中风险', high: '高风险', critical: '严重' };
```

- [ ] **Step 4: Render selected categories through the registry**

In `CategorySection.jsx`:

```jsx
const Renderer = getReportRenderer(category.renderer);
return <Renderer records={pageData.records} category={category} reportId={reportId} dataSource={dataSource} />;
```

Unknown renderer values must fall back to the generic table instead of failing the page.

- [ ] **Step 5: Run renderer and workspace tests**

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run src/components/reports/renderers src/components/reports/ReportWorkspace.test.jsx
npm run build
```

Expected: all tests pass and the production build completes.

- [ ] **Step 6: Commit baseline renderers**

```bash
git add web/src/components/reports/renderers web/src/components/reports/CategorySection.jsx
git commit -m "feat(web): render structured report records"
```

---

## Plan 2 Completion Gate

Run:

```bash
cd /home/ymj68520/projects/Forensics/TraceLens/web
npm test -- --run
npm run build
cd /home/ymj68520/projects/Forensics/TraceLens
git status --short
```

Expected:

- Frontend test harness passes.
- New and legacy report routes resolve correctly.
- Task and case links target the dedicated report workspace.
- Version history defaults to the latest ready version.
- Refresh recovers a generating job from backend version history.
- Directory navigation loads one category page at a time.
- Search has previous/next navigation and selects the hit page.
- Narrow layout exposes a directory drawer.
- Sensitive values remain visible.
- Unknown renderers fall back to a generic table.
- Git status does not show the unrelated MIUI document staged.

Next plan: `docs/superpowers/plans/2026-07-30-cross-platform-forensic-report-adapters.md`.
