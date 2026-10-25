import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import CreateTaskModal from './CreateTaskModal';
import { getPresetById } from '../../config/caseBackgroundPresets';

const mocks = vi.hoisted(() => ({
  dispatch: vi.fn(() => ({ unwrap: () => Promise.resolve({ id: 'synthetic-task' }) })),
  createTask: vi.fn((payload) => ({ type: 'synthetic/create', payload })),
}));
vi.mock('react-redux', () => ({ useDispatch: () => mocks.dispatch }));
vi.mock('../../store/taskSlice', () => ({
  createTask: mocks.createTask,
  fetchTasks: () => ({ type: 'fetch' }),
}));
vi.mock('../common/ToastContext', () => ({ useToast: () => ({ success: vi.fn() }) }));
vi.mock('../filters/FilterProfileSelector', () => ({ default: () => <div>filter profile</div> }));

beforeEach(() => vi.clearAllMocks());

test('a chosen preset fills the description and is submitted unchanged', async () => {
  render(<CreateTaskModal initialSource={{ image_path: '/evidence/disk.E01', android_source: 'tsk' }} />);

  fireEvent.click(screen.getByRole('button', { name: /选择预设背景/ }));
  const preset = getPresetById('telecom_fraud');
  fireEvent.click(screen.getByRole('button', { name: new RegExp(preset.label) }));

  const textarea = screen.getByPlaceholderText(/请输入案情描述/);
  expect(textarea).toHaveValue(preset.background);

  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  expect(mocks.createTask.mock.calls[0][0].case_description).toBe(preset.background);
});

test('applying a preset recommendation sets its filter profile', async () => {
  render(<CreateTaskModal initialSource={{ image_path: '/evidence/disk.E01', android_source: 'tsk' }} />);

  fireEvent.click(screen.getByRole('button', { name: /选择预设背景/ }));
  fireEvent.click(screen.getByRole('button', { name: '入侵与恶意代码' }));
  fireEvent.click(screen.getByRole('button', { name: /勒索软件攻击/ }));
  fireEvent.click(screen.getByRole('button', { name: '套用到分析场景' }));

  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  expect(mocks.createTask.mock.calls[0][0]).toMatchObject({
    case_description: getPresetById('ransomware').background,
    filter_profile: 'virus_intrusion',
  });
});

test('manual input still works when no preset is chosen', async () => {
  render(<CreateTaskModal initialSource={{ image_path: '/evidence/disk.E01', android_source: 'tsk' }} />);
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '一起自定义案件' } });
  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  expect(mocks.createTask.mock.calls[0][0].case_description).toBe('一起自定义案件');
  expect(screen.getByText('未使用预设，可手动输入')).toBeInTheDocument();
});
