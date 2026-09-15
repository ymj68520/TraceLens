import { afterAll, beforeAll, beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import tasksReducer, { fetchTasks } from '../store/taskSlice';
import casesReducer from '../store/caseSlice';
import settingsReducer from '../store/settingsSlice';
import intelligenceReducer from '../store/intelligenceSlice';
import filterReducer from '../store/filterSlice';
import type { ForensicTask } from '../types/api';
import CommandPalette from '../components/layout/CommandPalette';

const { navigateMock, setSearchParamsMock, urlParams } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
  setSearchParamsMock: vi.fn(),
  // Mutable holder so each test can stage the "current URL" that
  // useSearchParams reports (e.g. `/timeline?task_id=abc`).
  urlParams: { current: new URLSearchParams() },
}));

// Same approach as CommandPalette.test.tsx, plus a stubbed useSearchParams:
// the palette calls both hooks outside of a real <Routes> tree, so we capture
// the navigate target and control the task context ourselves.
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useSearchParams: () => [urlParams.current, setSearchParamsMock],
  };
});

const makeTask = (id: string, image: string): ForensicTask => ({
  id,
  image_path: image,
  status: 'completed',
});

/** Stage a browser URL of `?task_id=<id>` for the palette to pick up. */
function setTaskContext(taskId: string): void {
  urlParams.current = new URLSearchParams(`task_id=${taskId}`);
}

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

function renderPalette(tasks: ForensicTask[] = []) {
  const onOpenChange = vi.fn();
  const view = render(
    <Provider store={makeStore(tasks)}>
      <MemoryRouter>
        <CommandPalette open onOpenChange={onOpenChange} />
      </MemoryRouter>
    </Provider>,
  );
  return { onOpenChange, ...view };
}

beforeAll(() => {
  // Same jsdom gaps as CommandPalette.test.tsx: cmdk measures its list with
  // ResizeObserver and scrolls the selected item with scrollIntoView.
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
  urlParams.current = new URLSearchParams();
});

afterEach(() => {
  localStorage.clear();
  cleanup();
});

/**
 * Regression tests for CommandPalette's go(): it must parse href with
 * split('?') + URLSearchParams instead of `new URL(href).pathname`, which
 * used to throw InvalidURL on bare paths and broke every cross-page jump
 * while a task_id was in the URL.
 */
describe('CommandPalette go() — task context propagation', () => {
  it('passes the raw href through when the URL has no task_id', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette();

    await user.click(screen.getByRole('option', { name: /任务列表/ }));
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/tasks');

    await user.click(screen.getByRole('option', { name: /时间线/ }));
    expect(navigateMock).toHaveBeenCalledTimes(2);
    expect(navigateMock).toHaveBeenNthCalledWith(2, '/timeline');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('appends task_id when navigating to a TASK_CONTEXT page (时间线)', async () => {
    setTaskContext('abc');
    const user = userEvent.setup();
    renderPalette();

    await user.click(screen.getByRole('option', { name: /时间线/ }));
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/timeline?task_id=abc');
  });

  it('navigates to /dashboard without params and without throwing (original bug scenario)', async () => {
    setTaskContext('abc');
    const user = userEvent.setup();
    renderPalette();

    // The old `new URL(href).pathname` threw InvalidURL right here.
    await user.click(screen.getByRole('option', { name: /仪表盘/ }));
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith('/dashboard');
  });

  it('does not duplicate task_id for recent-task entries that already carry one', async () => {
    setTaskContext('abc');
    const user = userEvent.setup();
    renderPalette([makeTask('abc12345-rest', '/evidence/phone.img')]);

    await user.click(screen.getByText('phone.img'));
    expect(navigateMock).toHaveBeenCalledTimes(1);
    const href = navigateMock.mock.calls[0][0] as string;
    expect(href).toBe('/timeline?task_id=abc12345-rest');
    expect((href.match(/task_id=/g) ?? []).length).toBe(1);
  });

  it('stays stable when jumping off-context and back while a task_id is set', async () => {
    setTaskContext('abc');
    const user = userEvent.setup();
    const { onOpenChange } = renderPalette();

    await user.click(screen.getByRole('option', { name: /仪表盘/ }));
    await user.click(screen.getByRole('option', { name: /时间线/ }));
    expect(navigateMock.mock.calls.map((call) => call[0])).toEqual([
      '/dashboard',
      '/timeline?task_id=abc',
    ]);
    expect(onOpenChange).toHaveBeenCalledTimes(2);
    expect(onOpenChange).toHaveBeenNthCalledWith(2, false);
  });
});
