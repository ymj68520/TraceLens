import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import CreateTaskModal from './CreateTaskModal';

const mocks = vi.hoisted(() => ({ dispatch: vi.fn(() => ({ unwrap: () => Promise.resolve({ id: 'synthetic-task' }) })),
  createTask: vi.fn((payload) => ({ type: 'synthetic/create', payload })) }));
vi.mock('react-redux', () => ({ useDispatch: () => mocks.dispatch }));
vi.mock('../../store/taskSlice', () => ({ createTask: mocks.createTask, fetchTasks: () => ({ type: 'fetch' }) }));
vi.mock('../common/ToastContext', () => ({ useToast: () => ({ success: vi.fn() }) }));
vi.mock('../filters/FilterProfileSelector', () => ({ default: () => <div>Existing filter profile</div> }));
vi.mock('./RaidImageSource', () => ({ default: ({ onSource }) => <button type="button" onClick={() => onSource({
  image_path: '/synthetic/prepared/logical.img', image_source: 'raid', android_source: 'tsk',
  raid_job_id: 'a'.repeat(32), raid_manifest_sha256: 'b'.repeat(64), raid_allow_partial: false,
})}>Synthetic prepared source</button> }));

test('RAID uses existing task creation, case description and ordinary image scenarios', async () => {
  render(<CreateTaskModal />);
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'raid' } });
  expect(screen.getByText('Existing filter profile')).toBeInTheDocument();
  expect(screen.queryByPlaceholderText('/path/to/disk_image.dd or /path/to/image.E01')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Create Task' })).toBeDisabled();
  fireEvent.change(screen.getByPlaceholderText(/请输入案情描述/), { target: { value: 'Synthetic RAID case' } });
  fireEvent.click(screen.getByRole('button', { name: 'Synthetic prepared source' }));
  fireEvent.click(screen.getByRole('button', { name: 'Create Task' }));
  await waitFor(() => expect(mocks.createTask).toHaveBeenCalledOnce());
  expect(mocks.createTask.mock.calls[0][0]).toMatchObject({ android_source: 'tsk', image_source: 'raid',
    image_path: '/synthetic/prepared/logical.img', scenarios: [], case_description: 'Synthetic RAID case' });
});
