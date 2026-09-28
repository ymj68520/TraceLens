import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import CreateTaskModal from './CreateTaskModal';

vi.mock('react-redux', () => ({ useDispatch: () => vi.fn() }));
vi.mock('../common/ToastContext', () => ({ useToast: () => ({ success: vi.fn() }) }));

test('preflight can prefill a verified Android logical source without changing the case description', () => {
  render(<CreateTaskModal initialSource={{
    image_path: '/evidence/android', android_source: 'dir',
  }} />);
  expect(screen.getByPlaceholderText('/path/to/android_logical_extraction/')).toHaveValue('/evidence/android');
  expect(screen.getAllByRole('combobox')[0]).toHaveValue('dir');
  expect(screen.getByText(/由检材预检结果预填/)).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/请输入案情描述/)).toHaveValue('');
});

test('Android Backup preflight exposes a real source mode and runtime password field', () => {
  render(<CreateTaskModal initialSource={{
    image_path: '/evidence/backup.ab', android_source: 'android-backup',
    preflight_job_id: '1234567890abcdef1234567890abcdef',
    preflight_source_sha256: 'a'.repeat(64), preflight_detected_kind: 'android_backup',
  }} />);
  expect(screen.getAllByRole('combobox')[0]).toHaveValue('android-backup');
  expect(screen.getByPlaceholderText('/path/to/backup.ab')).toHaveValue('/evidence/backup.ab');
  expect(screen.getByPlaceholderText('未加密时留空')).toHaveAttribute('type', 'password');
});
