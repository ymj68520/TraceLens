import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import RaidImageSource from './RaidImageSource';

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../../services/api', () => ({ pythonApi: client }));
const base = '/api/evidence-intake/raid';
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });

test('existing task field selects opaque member IDs and returns a regular TSK image', async () => {
  const onSource = vi.fn();
  client.get.mockResolvedValueOnce({ groups: [{ name: 'synthetic-array', files: [
    { id: 'a'.repeat(24), name: 'member-z.raw', size: 1024 },
    { id: 'b'.repeat(24), name: 'member-a.raw', size: 1024 },
  ] }] });
  render(<RaidImageSource onSource={onSource} />);
  await screen.findByText('member-z.raw');
  expect(screen.getByRole('button', { name: '识别成员布局' })).toBeDisabled();
  screen.getAllByRole('checkbox').forEach((box) => fireEvent.click(box));
  client.post.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'queued' } });
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '识别成员布局' })); });
  expect(client.post).toHaveBeenLastCalledWith(`${base}/jobs`, { member_ids: ['a'.repeat(24), 'b'.repeat(24)] });
  client.get.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'awaiting_confirmation', inference: {
    status: 'UNIQUE_STRUCTURAL_CANDIDATE', candidates: [{ candidate_id: 'known', plan: { level: 5, layout: 2, chunk_size: 4096 } }],
  } } });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  client.post.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'queued' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '确认并准备系统镜像' })); });
  const source = { image_source: 'raid', android_source: 'tsk', image_path: '/synthetic/logical.img',
    raid_job_id: 'c'.repeat(32), raid_manifest_sha256: 'd'.repeat(64), raid_allow_partial: false };
  client.get.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'ready', task_source: source } });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(onSource).toHaveBeenLastCalledWith(source);
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

test('bounded search without a supported candidate cannot be confirmed', async () => {
  client.get.mockResolvedValueOnce({ groups: [{ name: 'test', files: [
    { id: 'a'.repeat(24), name: 'one.img', size: 1 }, { id: 'b'.repeat(24), name: 'two.img', size: 1 },
  ] }] });
  render(<RaidImageSource onSource={() => {}} />);
  await screen.findByText('one.img');
  screen.getAllByRole('checkbox').forEach((box) => fireEvent.click(box));
  client.post.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'queued' } });
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '识别成员布局' })); });
  client.get.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'awaiting_confirmation',
    inference: { status: 'SEARCH_LIMIT_REACHED', candidates: [] } } });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(screen.getByRole('button', { name: '确认并准备系统镜像' })).toBeDisabled();
});

test('ambiguous layouts require an explicit operator choice', async () => {
  client.get.mockResolvedValueOnce({ groups: [{ name: 'test', files: [
    { id: 'a'.repeat(24), name: 'one.img', size: 1 }, { id: 'b'.repeat(24), name: 'two.img', size: 1 },
  ] }] });
  render(<RaidImageSource onSource={() => {}} />);
  await screen.findByText('one.img');
  screen.getAllByRole('checkbox').forEach(box => fireEvent.click(box));
  client.post.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'queued' } });
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: '识别成员布局' })); });
  client.get.mockResolvedValueOnce({ job: { id: 'c'.repeat(32), status: 'awaiting_confirmation', inference: {
    status: 'AMBIGUOUS', candidates: [{ candidate_id: 'one', plan: { level: 5, layout: 2, chunk_size: 4096 } }],
  } } });
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(screen.getByRole('combobox', { name: 'RAID 布局候选' })).toHaveValue('');
  expect(screen.getByRole('button', { name: '确认并准备系统镜像' })).toBeDisabled();
  fireEvent.change(screen.getByRole('combobox', { name: 'RAID 布局候选' }), { target: { value: 'one' } });
  expect(screen.getByRole('button', { name: '确认并准备系统镜像' })).toBeEnabled();
});
