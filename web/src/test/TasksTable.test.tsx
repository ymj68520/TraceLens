import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '../store';
import TasksTable from '../components/tasks/TasksTable';
import type { ForensicCase, ForensicTask } from '../types/api';

const makeTask = (id: string, over: Partial<ForensicTask> = {}): ForensicTask => ({
  id,
  image_path: `/images/${id}.raw`,
  status: 'completed',
  priority: 'normal',
  progress: 40,
  created_at: '2024-01-15T08:00:00Z',
  ...over,
});

/** Twelve tasks with distinct creation times; task-12 is the newest. */
const twelveTasks = (): ForensicTask[] =>
  Array.from({ length: 12 }, (_, i) => {
    const n = i + 1;
    return makeTask(`task-${String(n).padStart(2, '0')}`, {
      created_at: `2024-03-01T${String(n).padStart(2, '0')}:00:00Z`,
    });
  });

interface SetupOptions {
  tasks?: ForensicTask[];
  taskCaseMap?: Record<string, ForensicCase>;
  selectedIds?: Set<string>;
}

function setup({ tasks = [], taskCaseMap = {}, selectedIds = new Set<string>() }: SetupOptions = {}) {
  const onToggleSelect = vi.fn();
  const onToggleSelectAll = vi.fn();
  const onCancel = vi.fn();
  const onDelete = vi.fn();
  const onJoinCase = vi.fn();
  const view = render(
    <Provider store={store}>
      <MemoryRouter>
        <TasksTable
          tasks={tasks}
          taskCaseMap={taskCaseMap}
          selectedIds={selectedIds}
          onToggleSelect={onToggleSelect}
          onToggleSelectAll={onToggleSelectAll}
          onCancel={onCancel}
          onDelete={onDelete}
          onJoinCase={onJoinCase}
        />
      </MemoryRouter>
    </Provider>,
  );
  return { onToggleSelect, onToggleSelectAll, onCancel, onDelete, onJoinCase, ...view };
}

const bodyRows = (container: HTMLElement): HTMLElement[] =>
  Array.from(container.querySelectorAll('tbody tr'));

/** "第 1–10 条，共 12 个任务" with all incidental whitespace collapsed. */
const rangeLabel = (): string => (screen.getByText(/共/).textContent ?? '').replace(/\s+/g, '');

describe('TasksTable — rendering', () => {
  it('renders one row per task with the image basename and id prefix', () => {
    const { container } = setup({ tasks: [makeTask('aaaaaaaa-1'), makeTask('bbbbbbbb-2')] });
    expect(bodyRows(container)).toHaveLength(2);
    expect(screen.getByText('aaaaaaaa-1.raw')).toBeInTheDocument();
    expect(screen.getByText('aaaaaaaa…')).toBeInTheDocument();
    expect(screen.getByText('bbbbbbbb-2.raw')).toBeInTheDocument();
  });

  it('renders the localized status badge', () => {
    setup({ tasks: [makeTask('task-done'), makeTask('task-run', { status: 'running' })] });
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('运行中')).toBeInTheDocument();
  });

  it('renders zero rows and a zeroed range for an empty task list', () => {
    const { container } = setup();
    expect(bodyRows(container)).toHaveLength(0);
    expect(rangeLabel()).toBe('第0–0条，共0个任务');
  });
});

describe('TasksTable — sorting', () => {
  it('clicking the created-time header flips the row order between desc and asc', async () => {
    const user = userEvent.setup();
    const tasks = [
      makeTask('task-old', { created_at: '2024-01-01T00:00:00Z' }),
      makeTask('task-new', { created_at: '2024-02-01T00:00:00Z' }),
    ];
    const { container } = setup({ tasks });
    const firstRowImage = () => bodyRows(container)[0]?.textContent ?? '';

    // Newest first by default (created, desc).
    expect(firstRowImage()).toContain('task-new.raw');

    await user.click(screen.getByRole('button', { name: /创建时间/ }));
    expect(firstRowImage()).toContain('task-old.raw');

    await user.click(screen.getByRole('button', { name: /创建时间/ }));
    expect(firstRowImage()).toContain('task-new.raw');
  });

  it('marks the active sort column with the accent class', async () => {
    const user = userEvent.setup();
    setup({ tasks: [makeTask('task-a')] });
    // SortTh remounts on every render (inline component), so re-query after clicks.
    expect(screen.getByRole('button', { name: /创建时间/ })).toHaveClass('text-accent-600');
    expect(screen.getByRole('button', { name: /进度/ })).not.toHaveClass('text-accent-600');

    await user.click(screen.getByRole('button', { name: /进度/ }));
    expect(screen.getByRole('button', { name: /进度/ })).toHaveClass('text-accent-600');
    expect(screen.getByRole('button', { name: /创建时间/ })).not.toHaveClass('text-accent-600');
  });
});

describe('TasksTable — pagination', () => {
  it('shows the first pageSize rows with the range label and disabled prev button', () => {
    const { container } = setup({ tasks: twelveTasks() });
    expect(bodyRows(container)).toHaveLength(10);
    expect(rangeLabel()).toBe('第1–10条，共12个任务');
    expect(screen.getByText('1 / 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '下一页' })).toBeEnabled();
  });

  it('next page shows the remaining rows and disables the next button', async () => {
    const user = userEvent.setup();
    const { container } = setup({ tasks: twelveTasks() });
    await user.click(screen.getByRole('button', { name: '下一页' }));
    expect(bodyRows(container)).toHaveLength(2);
    expect(bodyRows(container)[0].textContent).toContain('task-02.raw');
    expect(rangeLabel()).toBe('第11–12条，共12个任务');
    expect(screen.getByText('2 / 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '上一页' })).toBeEnabled();
  });

  it('prev page returns to the first page', async () => {
    const user = userEvent.setup();
    const { container } = setup({ tasks: twelveTasks() });
    await user.click(screen.getByRole('button', { name: '下一页' }));
    await user.click(screen.getByRole('button', { name: '上一页' }));
    expect(bodyRows(container)).toHaveLength(10);
    expect(rangeLabel()).toBe('第1–10条，共12个任务');
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled();
  });

  it('growing the page size shows every task on one page', async () => {
    const user = userEvent.setup();
    const { container } = setup({ tasks: twelveTasks() });
    await user.selectOptions(screen.getByLabelText('每页条数'), '50');
    expect(bodyRows(container)).toHaveLength(12);
    expect(rangeLabel()).toBe('第1–12条，共12个任务');
    expect(screen.getByText('1 / 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled();
  });
});

describe('TasksTable — selection', () => {
  it('row checkboxes report the taskId; non-completed tasks stay disabled', async () => {
    const user = userEvent.setup();
    const tasks = [makeTask('task-done'), makeTask('task-run', { status: 'running' })];
    const { onToggleSelect } = setup({ tasks });
    const doneBox = screen.getByLabelText('选择任务 task-done') as HTMLInputElement;
    const runBox = screen.getByLabelText('选择任务 task-run') as HTMLInputElement;
    expect(doneBox).toBeEnabled();
    expect(runBox).toBeDisabled();

    await user.click(doneBox);
    expect(onToggleSelect).toHaveBeenCalledTimes(1);
    expect(onToggleSelect).toHaveBeenCalledWith('task-done');
  });

  it('select-all checkbox reports the checked state and reflects completed selection', async () => {
    const user = userEvent.setup();
    const { onToggleSelectAll } = setup({ tasks: [makeTask('task-done')] });
    const selectAll = screen.getByLabelText('全选已完成任务') as HTMLInputElement;
    expect(selectAll).not.toBeChecked();

    await user.click(selectAll);
    expect(onToggleSelectAll).toHaveBeenCalledTimes(1);
    expect(onToggleSelectAll).toHaveBeenCalledWith(true);
  });

  it('header checkbox is checked once every completed task is selected', () => {
    setup({ tasks: [makeTask('task-done'), makeTask('task-run', { status: 'running' })], selectedIds: new Set(['task-done']) });
    expect(screen.getByLabelText('全选已完成任务')).toBeChecked();
  });
});

describe('TasksTable — row actions', () => {
  it('cancel / join-case / delete buttons carry the right taskId', async () => {
    const user = userEvent.setup();
    const tasks = [makeTask('task-run', { status: 'running' }), makeTask('task-done')];
    const { onCancel, onDelete, onJoinCase } = setup({ tasks });

    await user.click(screen.getByRole('button', { name: '取消任务 task-run' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledWith('task-run');

    await user.click(screen.getByRole('button', { name: '将任务 task-done 加入案件' }));
    expect(onJoinCase).toHaveBeenCalledTimes(1);
    expect(onJoinCase).toHaveBeenCalledWith('task-done');

    await user.click(screen.getByRole('button', { name: '删除任务 task-done' }));
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith('task-done');
  });

  it('shows the owning case as a link and hides join-case for tasks already in a case', () => {
    const tasks = [makeTask('task-done')];
    const taskCaseMap = { 'task-done': { id: 'case-1', name: '银行卡案件' } as ForensicCase };
    setup({ tasks, taskCaseMap });
    expect(screen.getByRole('link', { name: '银行卡案件' })).toHaveAttribute('href', '/cases');
    expect(screen.queryByRole('button', { name: '将任务 task-done 加入案件' })).not.toBeInTheDocument();
  });

  it('hides the cancel button unless the task is running', () => {
    setup({ tasks: [makeTask('task-done')] });
    expect(screen.queryByRole('button', { name: '取消任务 task-done' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除任务 task-done' })).toBeInTheDocument();
  });
});
