import { afterAll, beforeAll, beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import tasksReducer, { fetchTasks } from '../store/taskSlice';
import casesReducer from '../store/caseSlice';
import settingsReducer, { updateSettings } from '../store/settingsSlice';
import intelligenceReducer from '../store/intelligenceSlice';
import filterReducer from '../store/filterSlice';
import type { ForensicTask } from '../types/api';
import CommandPalette from '../components/layout/CommandPalette';

const { navigateMock } = vi.hoisted(() => ({ navigateMock: vi.fn() }));

// The palette calls useNavigate() outside of the <Routes> tree; keep every other
// router export (MemoryRouter, useSearchParams, …) as the real implementation.
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});

const makeTask = (id: string, image: string): ForensicTask => ({
  id,
  image_path: image,
  status: 'completed',
});

/** Fresh store per test with the real reducers; optionally seeded with tasks. */
function makeStore(tasks: ForensicTask[] = []) {
  const store = configureStore({
    reducer: {
      tasks: tasksReducer,
      cases: casesReducer,
      settings: settingsReducer,
      intelligence: intelligenceReducer,
      filter: filterReducer,
    },
  });
  if (tasks.length > 0) {
    store.dispatch(fetchTasks.fulfilled({ tasks }, 'test-request', {}));
  }
  return store;
}

function renderPalette(open = true, tasks: ForensicTask[] = []) {
  const onOpenChange = vi.fn();
  const view = render(
    <Provider store={makeStore(tasks)}>
      <MemoryRouter initialEntries={['/']}>
        <CommandPalette open={open} onOpenChange={onOpenChange} />
      </MemoryRouter>
    </Provider>,
  );
  return { onOpenChange, ...view };
}

beforeAll(() => {
  // jsdom ships neither: cmdk's list measures itself with ResizeObserver and
  // scrolls the selected item with scrollIntoView.
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
  Element.prototype.scrollIntoView = () => {};
});

afterAll(() => {
  vi.unstubAllGlobals();
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

beforeEach(() => {
  navigateMock.mockClear();
});

afterEach(() => {
  localStorage.clear();
  cleanup();
});

describe('CommandPalette — hotkey', () => {
  it('Ctrl+K asks to open the palette while closed', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette(false);
    await user.keyboard('{Control>}k{/Control}');
    expect(onOpenChange).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it('Ctrl+K asks to close the palette while open', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette(true);
    await user.keyboard('{Control>}k{/Control}');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('CommandPalette — rendering', () => {
  it('renders the search input with grouped navigation entries', () => {
    renderPalette();
    expect(screen.getByPlaceholderText('搜索页面、任务…')).toBeInTheDocument();
    expect(screen.getByText('概览')).toBeInTheDocument();
    expect(screen.getByText('仪表盘')).toBeInTheDocument();
    expect(screen.getByText('任务列表')).toBeInTheDocument();
    expect(screen.getByText('取证分析')).toBeInTheDocument();
    expect(screen.getByText('情报与图谱')).toBeInTheDocument();
    expect(screen.getByText('系统')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
  });

  it('omits the terminal entry unless showTerminal is enabled', async () => {
    renderPalette();
    expect(screen.queryByText('系统终端')).not.toBeInTheDocument();

    const store = makeStore();
    store.dispatch(updateSettings({ showTerminal: true }));
    cleanup();
    render(
      <Provider store={store}>
        <MemoryRouter initialEntries={['/']}>
          <CommandPalette open onOpenChange={vi.fn()} />
        </MemoryRouter>
      </Provider>,
    );
    expect(screen.getByText('系统终端')).toBeInTheDocument();
  });

  it('hides the recent-tasks group while the store has no tasks', () => {
    renderPalette();
    expect(screen.queryByText('最近任务')).not.toBeInTheDocument();
  });

  it('lists seeded tasks under 最近任务 and deep-links into the timeline', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette(true, [
      makeTask('abc12345-rest', '/evidence/chat.img'),
    ]);
    expect(screen.getByText('最近任务')).toBeInTheDocument();
    expect(screen.getByText('chat.img')).toBeInTheDocument();
    expect(screen.getByText('abc12345')).toBeInTheDocument(); // id prefix

    await user.click(screen.getByText('chat.img'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/timeline?task_id=abc12345-rest');
  });
});

describe('CommandPalette — filtering and selection', () => {
  it('filters entries while typing and hides emptied groups', async () => {
    const user = userEvent.setup();
    renderPalette();
    const input = screen.getByPlaceholderText('搜索页面、任务…');
    await user.type(input, '时间线');

    expect(screen.getByRole('option', { name: /时间线/ })).toBeInTheDocument();
    expect(screen.queryByText('仪表盘')).not.toBeInTheDocument();
    // A group whose items all got filtered out is rendered hidden (on the group container).
    expect(screen.getByText('概览').closest('[cmdk-group]')).toHaveAttribute('hidden');
    expect(screen.getByText('取证分析').closest('[cmdk-group]')).not.toHaveAttribute('hidden');
  });

  it('shows the empty state when nothing matches', async () => {
    const user = userEvent.setup();
    renderPalette();
    expect(screen.queryByText('没有匹配的结果')).not.toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('搜索页面、任务…'), '不存在的页面');
    expect(screen.getByText('没有匹配的结果')).toBeInTheDocument();
  });

  it('clicking an entry navigates and closes the palette', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette();
    await user.click(screen.getByText('任务列表'));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/tasks');
  });

  it('Enter on the best match navigates too', async () => {
    const user = userEvent.setup();
    renderPalette();
    const input = screen.getByPlaceholderText('搜索页面、任务…');
    await user.type(input, '时间线');
    await user.keyboard('{Enter}');
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/timeline');
  });
});
