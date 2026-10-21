import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import EvidencePreflightPanel from './EvidencePreflightPanel';
import {
  getEvidencePreflight,
  listEvidenceCandidates,
  startEvidencePreflight,
} from '../../services/evidenceIntakeService';

vi.mock('../../services/evidenceIntakeService', () => ({
  listEvidenceCandidates: vi.fn(),
  startEvidencePreflight: vi.fn(),
  getEvidencePreflight: vi.fn(),
  cancelEvidencePreflight: vi.fn(),
  evidenceManifestUrl: (id) => `/manifest/${id}`,
}));

beforeEach(() => {
  vi.clearAllMocks();
  listEvidenceCandidates.mockResolvedValue({ candidates: [{
    id: 'candidate-a', name: 'unknown.mfc', kind: 'vendor_container_unknown',
    adapter: null, confidence: 'extension_only',
  }] });
});

test('quick preflight keeps proprietary evidence unsupported and does not claim analysis', async () => {
  const user = userEvent.setup();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: 'job-a', status: 'completed', detected: { kind: 'vendor_container_unknown', adapter: null },
    integrity_status: 'not_calculated', file_count: 1, bytes_read: 0,
  } });
  render(<EvidencePreflightPanel />);
  expect(await screen.findByRole('combobox', { name: '候选检材' })).toHaveValue('candidate-a');
  await user.click(screen.getByRole('button', { name: '快速识别' }));
  await waitFor(() => expect(startEvidencePreflight).toHaveBeenCalledWith('candidate-a', false));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('无，需现场确认');
  expect(screen.getByText(/预检完成不等于取证或分析完成/)).toBeInTheDocument();
});

test('full hash runs as a background job and displays source digest', async () => {
  const user = userEvent.setup();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: 'job-b', status: 'queued', integrity_status: 'not_calculated',
  } });
  getEvidencePreflight.mockResolvedValue({ job: {
    id: 'job-b', status: 'completed', integrity_status: 'verified',
    detected: { kind: 'raw_image_candidate', adapter: 'tsk_probe_required' },
    sha256: 'digest', file_count: 1, bytes_read: 10,
  } });
  render(<EvidencePreflightPanel />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  await waitFor(() => expect(startEvidencePreflight).toHaveBeenCalledWith('candidate-a', true));
  expect(await screen.findByText(/源文件 SHA-256：digest/, {}, { timeout: 3000 })).toBeInTheDocument();
});

test('only a verified supported logical source can prefill a new Android Task', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: 'job-c', status: 'completed', integrity_status: 'manifest_hashed',
    source_path: '/evidence/android', detected: { kind: 'android_logical_tree', adapter: 'dir' },
    file_count: 1, bytes_read: 100,
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith({ image_path: '/evidence/android', android_source: 'dir' });
});

test('verified Android TAR prefill carries immutable preflight identity', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/phone.tar', sha256: 'a'.repeat(64),
    detected: { kind: 'tar_container', adapter: 'tar', analysis_state: 'CAN_NORMALIZE' },
    archive: { inspected: true, ready: true, entries: 5, root_mapping: 'archive_root',
      encryption_status: 'none' },
    file_count: 1, bytes_read: 200,
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('归档成员：5');
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith({
    image_path: '/evidence/phone.tar', android_source: 'tar',
    preflight_job_id: '1234567890abcdef1234567890abcdef',
    preflight_source_sha256: 'a'.repeat(64), preflight_detected_kind: 'tar_container',
  });
});

test('verified Android userdata image prefill binds hash and detected kind', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/userdata.img', sha256: 'c'.repeat(64),
    detected: { kind: 'android_userdata_image', adapter: 'filesystem-image' },
    image: { ready: true, reader: 'qnxprobe-1.34', selected_partition: {
      kind: 'f2fs', base: 0, encryption: { state: 'UNENCRYPTED' },
    }, android_candidates: [{}] },
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith({
    image_path: '/evidence/userdata.img', android_source: 'filesystem-image',
    preflight_job_id: '1234567890abcdef1234567890abcdef',
    preflight_source_sha256: 'c'.repeat(64), preflight_detected_kind: 'android_userdata_image',
  });
});

test('locked userdata offers only a locked-coverage Task', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/userdata.img', sha256: 'd'.repeat(64),
    detected: { kind: 'android_userdata_locked', adapter: 'filesystem-image' },
    image: { ready: false, reader: 'qnxprobe-1.34', selected_partition: {
      kind: 'f2fs', base: 0, locked: true, encryption: { state: 'LOCKED' },
    }, android_candidates: [{}] },
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('不会尝试解析密文');
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith(expect.objectContaining({
    preflight_detected_kind: 'android_userdata_locked', android_source: 'filesystem-image',
  }));
});

test('validated sparse userdata carries the exact normalization plan', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  listEvidenceCandidates.mockResolvedValue({ candidates: [{
    id: 'sparse-one', name: 'userdata.sparse', kind: 'android_sparse_image', adapter: null,
  }] });
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/userdata.sparse', sha256: 'a'.repeat(64), selected_slot: 0,
    detected: { kind: 'android_sparse_userdata', adapter: 'android-container' },
    container: { ready: true, kind: 'ANDROID_SPARSE_USERDATA', plan_sha256: 'b'.repeat(64),
      sparse: { validation_status: 'VALIDATED', expanded_size: 268435456, chunk_count: 6 },
      userdata_preflight: { selected_partition: { kind: 'f2fs' } } },
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('F2FS');
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith(expect.objectContaining({
    android_source: 'android-container', preflight_plan_sha256: 'b'.repeat(64),
    preflight_detected_kind: 'android_sparse_userdata', preflight_selected_slot: 0,
  }));
});

test('super inventory never claims userdata analysis', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  listEvidenceCandidates.mockResolvedValue({ candidates: [{
    id: 'super-one', name: 'super.img', kind: 'raw_image_candidate', adapter: null,
  }] });
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/super.img', sha256: 'c'.repeat(64), selected_slot: 0,
    detected: { kind: 'android_raw_super', adapter: 'android-container' },
    container: { ready: true, kind: 'ANDROID_RAW_SUPER', selected_slot: 0,
      plan_sha256: 'd'.repeat(64), super_inventory: { metadata_version: [10, 0],
        metadata_slot_count: 2, partition_count: 1,
        partitions: [{ name: 'system_a', size: 8388608, group_name: 'main_a' }] } },
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('来源中未包含');
  await user.click(await screen.findByRole('button', { name: '建立系统分区规范化任务' }));
  expect(onCreateTask).toHaveBeenCalledWith(expect.objectContaining({
    android_source: 'android-container', preflight_detected_kind: 'android_raw_super',
  }));
});

test('locked Android Backup never offers one-click analysis', async () => {
  const user = userEvent.setup();
  startEvidencePreflight.mockResolvedValue({ job: {
    id: 'job-locked', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/phone.ab', sha256: 'b'.repeat(64),
    detected: { kind: 'android_backup_encrypted', adapter: null, encryption_status: 'locked' },
    file_count: 1, bytes_read: 50,
  } });
  render(<EvidencePreflightPanel onCreateTask={vi.fn()} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(screen.getByTestId('evidence-preflight-result')).toHaveTextContent('加密锁定');
  expect(screen.queryByRole('button', { name: '按此来源新建 安卓分析任务' })).not.toBeInTheDocument();
});

test('password-unlocked Android Backup carries only runtime secret to Task form', async () => {
  const user = userEvent.setup();
  const onCreateTask = vi.fn();
  listEvidenceCandidates.mockResolvedValue({ candidates: [{
    id: 'ab-candidate', name: 'backup.ab', kind: 'android_backup_encrypted', adapter: null,
  }] });
  startEvidencePreflight.mockResolvedValue({ job: {
    id: '1234567890abcdef1234567890abcdef', status: 'completed', integrity_status: 'verified',
    source_path: '/evidence/backup.ab', sha256: 'b'.repeat(64), password_supplied: true,
    detected: { kind: 'android_backup_encrypted', adapter: 'android-backup', analysis_state: 'CAN_NORMALIZE' },
    archive: { inspected: true, ready: true, entries: 5, root_mapping: 'adb_apps',
      encryption_status: 'unlocked' },
  } });
  render(<EvidencePreflightPanel onCreateTask={onCreateTask} />);
  await screen.findByRole('combobox', { name: '候选检材' });
  await user.type(screen.getByLabelText(/归档\/备份密码/), 'one-time-secret');
  await user.click(screen.getByRole('button', { name: '后台计算完整 SHA-256' }));
  expect(startEvidencePreflight).toHaveBeenCalledWith('ab-candidate', true, 'one-time-secret');
  await user.click(await screen.findByRole('button', { name: '按此来源新建 安卓分析任务' }));
  expect(onCreateTask).toHaveBeenCalledWith(expect.objectContaining({
    android_source: 'android-backup', backup_password: 'one-time-secret',
    preflight_detected_kind: 'android_backup_encrypted',
  }));
});
