import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import Layout from './Layout';

vi.mock('../common/TaskSelector', () => ({ default: () => null }));

// Feature switches drive the MVP nav trims (mvp-phase1-acceptance §4.3).
// Tests default to the trimmed MVP form; nav-contract tests flip
// combined_case_enabled back on via featuresState.
const featuresState = vi.hoisted(() => ({ value: null }));
vi.mock('../../services/featuresService', () => ({
  FEATURE_DEFAULTS: {
    event_llm_analysis_enabled: false,
    combined_case_enabled: false,
    workbench_llm_enabled: false,
    memory_forensics_enabled: false,
    oss_analysis_enabled: false,
  },
  fetchFeatures: () =>
    Promise.resolve(
      featuresState.value ?? {
        event_llm_analysis_enabled: false,
        combined_case_enabled: false,
        workbench_llm_enabled: false,
        memory_forensics_enabled: false,
        oss_analysis_enabled: false,
      },
    ),
}));

function renderLayout(route) {
  const store = configureStore({
    reducer: {
      settings: () => ({ theme: 'light', showTerminal: false, language: 'zh' }),
      ui: () => ({ sidebarOpen: true }),
    },
  });

  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[route]}>
        <Layout><div>report content</div></Layout>
      </MemoryRouter>
    </Provider>,
  );
}

test('links to evidence analysis with the current task query contract', () => {
  renderLayout('/files?task_id=task-1');

  expect(screen.getByRole('link', { name: '证据研判' })).toHaveAttribute(
    'href',
    '/case-intelligence?task_id=task-1',
  );
});

test('links to the analysis center with the current task query contract', async () => {
  featuresState.value = { event_llm_analysis_enabled: true, combined_case_enabled: true, workbench_llm_enabled: true };
  renderLayout('/files?task_id=task-1');

  expect(await screen.findByRole('link', { name: '研判中心' })).toHaveAttribute(
    'href',
    '/analysis-center?task_id=task-1',
  );
});

test('renders 证据研判 before 研判中心 in the sidebar', async () => {
  featuresState.value = { event_llm_analysis_enabled: true, combined_case_enabled: true, workbench_llm_enabled: true };
  renderLayout('/dashboard');

  // wait for the async feature fetch to un-hide the combined-case entries
  await screen.findByRole('link', { name: '研判中心' });
  const links = screen.getAllByRole('link');
  const evidenceIdx = links.findIndex((l) => l.textContent === '证据研判');
  const centerIdx = links.findIndex((l) => l.textContent === '研判中心');

  expect(evidenceIdx).toBeGreaterThanOrEqual(0);
  expect(centerIdx).toBeGreaterThanOrEqual(0);
  expect(evidenceIdx).toBeLessThan(centerIdx);
});

test('keeps the analysis center navigation active', async () => {
  featuresState.value = { event_llm_analysis_enabled: true, combined_case_enabled: true, workbench_llm_enabled: true };
  renderLayout('/analysis-center');

  const reportNav = await screen.findByRole('link', { name: '研判中心' });
  expect(reportNav).toHaveAttribute('href', '/analysis-center');
  expect(reportNav).toHaveClass('bg-primary-500/20');
  expect(reportNav.querySelector('.bg-primary-400')).not.toBeNull();
  expect(screen.getByRole('heading', { name: '研判中心' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '仪表盘' })).not.toBeInTheDocument();
});

test('MVP default hides the combined-case nav entries (mvp-phase1-acceptance §4.3)', async () => {
  featuresState.value = null;
  renderLayout('/dashboard');

  await waitFor(() => {
    expect(screen.getByRole('link', { name: '证据研判' })).toBeInTheDocument();
  });
  expect(screen.queryByRole('link', { name: '案件组合' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: '研判中心' })).not.toBeInTheDocument();
});

test('MVP default hides the memory and OSS nav entries (mvp-phase1-acceptance §4.6/§4.7)', async () => {
  featuresState.value = null;
  renderLayout('/dashboard');

  await waitFor(() => {
    expect(screen.getByRole('link', { name: '证据研判' })).toBeInTheDocument();
  });
  expect(screen.queryByRole('link', { name: '内存取证' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'OSS 分析' })).not.toBeInTheDocument();
});

test('re-enabled flags restore the memory and OSS nav entries (§4.6/§4.7 escape hatch)', async () => {
  featuresState.value = {
    event_llm_analysis_enabled: true,
    combined_case_enabled: true,
    workbench_llm_enabled: true,
    memory_forensics_enabled: true,
    oss_analysis_enabled: true,
  };
  renderLayout('/dashboard');

  expect(await screen.findByRole('link', { name: '内存取证' })).toHaveAttribute('href', '/memory');
  expect(screen.getByRole('link', { name: 'OSS 分析' })).toHaveAttribute('href', '/oss');
});

test('keeps the investigation workbench navigation active on its report subroute', () => {
  renderLayout('/investigation/report?task_id=task-1');

  const investigationNav = screen.getByRole('link', { name: '调查工作台' });
  // task 上下文随导航保留
  expect(investigationNav).toHaveAttribute('href', '/investigation?task_id=task-1');
  expect(investigationNav).toHaveClass('bg-primary-500/20');
  // 顶栏标题必须跟随所属导航，而不是回退成“仪表盘”
  expect(screen.getByRole('heading', { name: '调查工作台' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '仪表盘' })).not.toBeInTheDocument();
});
