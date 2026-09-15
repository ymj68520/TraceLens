import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import store from '../store';
import NotFound from '../pages/NotFound';

function renderNotFound(path = '/missing/page') {
  // NotFound reads the current path for the mono path display.
  window.history.replaceState({}, '', path);
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[path]}>
        <NotFound />
      </MemoryRouter>
    </Provider>,
  );
}

describe('NotFound', () => {
  it('renders the 404 headline digits and brand mark', () => {
    renderNotFound();
    // The three digits are separate spans (staggered entrance animation).
    expect(
      screen.getByText((_, el) => el?.textContent === '404' && el.classList.contains('font-mono')),
    ).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'TraceLens' })).toBeInTheDocument();
  });

  it('shows the requested path in the hint', () => {
    renderNotFound('/tools/nope');
    expect(screen.getByText('/tools/nope')).toBeInTheDocument();
  });

  it('links back to the dashboard', () => {
    renderNotFound();
    const back = screen.getByRole('link', { name: /返回仪表盘/ });
    expect(back).toHaveAttribute('href', '/dashboard');
  });

  it('dispatches a Ctrl+K keydown when the search button is clicked', () => {
    const spy = vi.spyOn(window, 'dispatchEvent');
    renderNotFound();
    screen.getByRole('button', { name: /全局搜索/ }).click();
    const calls = spy.mock.calls;
    const event = calls[calls.length - 1][0] as KeyboardEvent;
    expect(event.type).toBe('keydown');
    expect(event.key.toLowerCase()).toBe('k');
    expect(event.ctrlKey).toBe(true);
    expect(event.metaKey).toBe(true);
    spy.mockRestore();
  });
});
