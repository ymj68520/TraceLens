import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';
import CreateTaskModal from './CreateTaskModal';

const mocks = vi.hoisted(() => ({ dispatch: vi.fn(() => ({ unwrap: () => Promise.resolve({ id: 'cloud-task' }) })),
  createTask: vi.fn(payload => ({ type: 'synthetic/create', payload })) }));
vi.mock('react-redux', () => ({ useDispatch: () => mocks.dispatch }));
vi.mock('../../store/taskSlice', () => ({ createTask: mocks.createTask, fetchTasks: () => ({ type: 'fetch' }) }));
vi.mock('../common/ToastContext', () => ({ useToast: () => ({ success: vi.fn() }) }));
vi.mock('../filters/FilterProfileSelector', () => ({ default: () => <div>原有筛选流程</div> }));
beforeEach(() => vi.clearAllMocks());
const source = { image_path: '/evidence/file_m-x_system.raw.tar.gz', android_source: 'aliyun-image',
  preflight_job_id: 'a'.repeat(32), preflight_source_sha256: 'b'.repeat(64),
  preflight_detected_kind: 'aliyun_raw_export', scenarios: ['android'], platform_analyze: false };

test('Aliyun option submits the same task API with Linux and existing filtering', async () => {
  render(<CreateTaskModal initialSource={source} />);
  expect(screen.getAllByRole('combobox')[0]).toHaveValue('aliyun-image');
  expect(screen.getByText('原有筛选流程')).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '云系统盘核查' } });
  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  expect(mocks.createTask.mock.calls[0][0]).toMatchObject({
    image_path: source.image_path, android_source: 'aliyun-image', scenarios: ['linux'], platform_analyze: true,
    filter_profile: 'general_forensics', preflight_source_sha256: source.preflight_source_sha256,
  });
});

test('editing a preflight source invalidates its identity before submission', async () => {
  render(<CreateTaskModal initialSource={source} />);
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: '云系统盘核查' } });
  fireEvent.change(screen.getByPlaceholderText('/path/to/file_m-xxx_system.raw.tar.gz'), { target: { value: '/evidence/changed.tar.gz' } });
  fireEvent.click(screen.getByRole('button', { name: '创建任务' }));
  expect(await screen.findByText('请先在检材预检中完成完整 SHA-256，再按此来源创建任务')).toBeInTheDocument();
  expect(mocks.createTask).not.toHaveBeenCalled();
});
