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

test.each([
  ['/reports/task/task-1', '/reports/task/task-1'],
  ['/reports/case/case-1', '/reports/case/case-1'],
])('keeps the report navigation active at %s', (route, expectedHref) => {
  renderLayout(route);

  const reportNav = screen.getByRole('link', { name: '研判中心' });
  expect(reportNav).toHaveAttribute('href', expectedHref);
  expect(reportNav).toHaveClass('bg-primary-500/20');
  expect(reportNav.querySelector('.bg-primary-400')).not.toBeNull();
  expect(screen.getByRole('heading', { name: '研判中心' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '仪表盘' })).not.toBeInTheDocument();
});
