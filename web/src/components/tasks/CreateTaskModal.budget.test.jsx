import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import CreateTaskModal from './CreateTaskModal';

const mocks = vi.hoisted(() => ({
  dispatch: vi.fn(() => ({ unwrap: () => Promise.resolve({ id: 'budget-task' }) })),
  createTask: vi.fn((payload) => ({ type: 'synthetic/create', payload })),
}));
vi.mock('react-redux', () => ({ useDispatch: () => mocks.dispatch }));
vi.mock('../../store/taskSlice', () => ({
  createTask: mocks.createTask,
  fetchTasks: () => ({ type: 'fetch' }),
}));
vi.mock('../common/ToastContext', () => ({ useToast: () => ({ success: vi.fn() }) }));
vi.mock('../filters/FilterProfileSelector', () => ({ default: () => <div>filter profile</div> }));

const source = { image_path: '/evidence/disk.E01', android_source: 'tsk' };

const submit = async () => {
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '一起预算测试案件' } });
  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  return mocks.createTask.mock.calls[0][0];
};

beforeEach(() => vi.clearAllMocks());

test('the budget defaults to the server setting and is not sent', async () => {
  render(<CreateTaskModal initialSource={source} />);

  expect(screen.getByLabelText('分析文件上限')).toHaveValue('default');
  const payload = await submit();

  expect(payload).not.toHaveProperty('llm_max_files');
  expect(payload.llm_analyze).toBe(true);
});

test('a preset budget is sent as llm_max_files', async () => {
  render(<CreateTaskModal initialSource={source} />);

  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: '300' } });
  const payload = await submit();

  expect(payload.llm_max_files).toBe(300);
});

test('a custom budget is validated and sent as a number', async () => {
  render(<CreateTaskModal initialSource={source} />);

  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: 'custom' } });
  fireEvent.change(screen.getByLabelText('自定义分析文件上限'), { target: { value: '1234' } });
  const payload = await submit();

  expect(payload.llm_max_files).toBe(1234);
});

test('an invalid custom budget blocks submission with a readable message', async () => {
  const { container } = render(<CreateTaskModal initialSource={source} />);

  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: 'custom' } });
  fireEvent.change(screen.getByLabelText('自定义分析文件上限'), { target: { value: '0' } });
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '一起预算测试案件' } });
  // Native min/max constraint validation would stop the click before React's
  // handler; dispatch submit directly to exercise our own guard, which is what
  // protects programmatic callers and browsers without constraint validation.
  fireEvent.submit(container.querySelector('form'));

  expect(await screen.findByText(/分析文件上限需在 1–100000 之间/)).toBeInTheDocument();
  expect(mocks.createTask).not.toHaveBeenCalled();
});

test('an empty custom budget blocks submission instead of inheriting silently', async () => {
  const { container } = render(<CreateTaskModal initialSource={source} />);

  fireEvent.change(screen.getByLabelText('分析文件上限'), { target: { value: 'custom' } });
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '一起预算测试案件' } });
  fireEvent.submit(container.querySelector('form'));

  expect(await screen.findByText(/分析文件上限需填写正整数/)).toBeInTheDocument();
  expect(mocks.createTask).not.toHaveBeenCalled();
});

test('the picker reflects a pre-filled task budget', () => {
  render(<CreateTaskModal initialSource={{ ...source, llm_max_files: 750 }} />);

  expect(screen.getByLabelText('分析文件上限')).toHaveValue('custom');
  expect(screen.getByLabelText('自定义分析文件上限')).toHaveValue(750);
});
