import { configureStore } from '@reduxjs/toolkit';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import Layout from './Layout';

vi.mock('../common/TaskSelector', () => ({ default: () => null }));

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

test('links to the analysis center with the current task query contract', () => {
  renderLayout('/files?task_id=task-1');

  expect(screen.getByRole('link', { name: '研判中心' })).toHaveAttribute(
    'href',
    '/analysis-center?task_id=task-1',
  );
});

test('renders 证据研判 before 研判中心 in the sidebar', () => {
  renderLayout('/dashboard');

  const links = screen.getAllByRole('link');
  const evidenceIdx = links.findIndex((l) => l.textContent === '证据研判');
  const centerIdx = links.findIndex((l) => l.textContent === '研判中心');

  expect(evidenceIdx).toBeGreaterThanOrEqual(0);
  expect(centerIdx).toBeGreaterThanOrEqual(0);
  expect(evidenceIdx).toBeLessThan(centerIdx);
});

test('keeps the analysis center navigation active', () => {
  renderLayout('/analysis-center');

  const reportNav = screen.getByRole('link', { name: '研判中心' });
  expect(reportNav).toHaveAttribute('href', '/analysis-center');
  expect(reportNav).toHaveClass('bg-primary-500/20');
  expect(reportNav.querySelector('.bg-primary-400')).not.toBeNull();
  expect(screen.getByRole('heading', { name: '研判中心' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '仪表盘' })).not.toBeInTheDocument();
});
