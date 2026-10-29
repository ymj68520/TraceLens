import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import VersionHistory from './VersionHistory';

const versionOne = { report_id: 'r1', version: 1, status: 'ready', generated_at: '2026-10-18T10:00:00Z', report_kind: 'deterministic' };
const versionTwo = { report_id: 'r2', version: 2, status: 'generating', progress: 20, generated_at: '2026-10-19T10:00:00Z', report_kind: 'llm_generation' };
const versionThree = { report_id: 'r3', version: 3, status: 'ready', generated_at: '2026-10-20T10:00:00Z', report_kind: 'llm_generation' };

test('selects the version clicked in the history', () => {
  const onSelect = vi.fn();
  render(<VersionHistory versions={[versionTwo, versionOne]} selectedVersion={versionTwo} onSelect={onSelect} />);

  fireEvent.click(screen.getByRole('radio', { name: '版本 1' }));

  expect(onSelect).toHaveBeenCalledWith(versionOne);
});

test('selects version via dropdown select', () => {
  const onSelect = vi.fn();
  render(<VersionHistory versions={[versionThree, versionTwo, versionOne]} selectedVersion={versionThree} onSelect={onSelect} />);

  const dropdown = screen.getByRole('combobox', { name: '选择报告版本' });
  fireEvent.change(dropdown, { target: { value: 'r1' } });

  expect(onSelect).toHaveBeenCalledWith(versionOne);
});

test('navigates to older/newer version via stepper buttons', () => {
  const onSelect = vi.fn();
  // With versionTwo selected: older is versionOne, newer is versionThree
  render(<VersionHistory versions={[versionThree, versionTwo, versionOne]} selectedVersion={versionTwo} onSelect={onSelect} />);

  const prevBtn = screen.getByRole('button', { name: /上一版/ });
  fireEvent.click(prevBtn);
  expect(onSelect).toHaveBeenCalledWith(versionOne);

  const nextBtn = screen.getByRole('button', { name: /下一版/ });
  fireEvent.click(nextBtn);
  expect(onSelect).toHaveBeenCalledWith(versionThree);
});

test('allows jumping back to latest version when viewing older version', () => {
  const onSelect = vi.fn();
  render(<VersionHistory versions={[versionThree, versionTwo, versionOne]} selectedVersion={versionOne} onSelect={onSelect} />);

  const jumpBtn = screen.getByRole('button', { name: /跳回最新/ });
  fireEvent.click(jumpBtn);

  expect(onSelect).toHaveBeenCalledWith(versionThree);
});

test('toggles expandable drawer to view all versions and search', () => {
  const onSelect = vi.fn();
  render(<VersionHistory versions={[versionThree, versionTwo, versionOne]} selectedVersion={versionThree} onSelect={onSelect} />);

  const toggleBtn = screen.getByRole('button', { name: /完整目录/ });
  fireEvent.click(toggleBtn);

  expect(screen.getByPlaceholderText('搜索版本号 / 标题…')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /收起列表/ })).toBeInTheDocument();
});
