import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import CaseBackgroundField, { CaseBackgroundPresetPicker } from './CaseBackgroundField';
import { CASE_BACKGROUND_PRESETS, getPresetById } from '../../config/caseBackgroundPresets';

test('picker writes the whole preset background into the field', () => {
  const onChange = vi.fn();
  render(<CaseBackgroundField value="" onChange={onChange} />);

  fireEvent.click(screen.getByRole('button', { name: /选择预设背景/ }));
  const preset = getPresetById('telecom_fraud');
  // 电信网络诈骗 is in the first group, visible without switching tabs.
  fireEvent.click(screen.getByRole('button', { name: new RegExp(preset.label) }));

  expect(onChange).toHaveBeenCalledWith(preset.background);
});

test('selected preset is announced and survives manual edits as custom', () => {
  const preset = getPresetById('homicide');
  const { rerender } = render(<CaseBackgroundPresetPicker value={preset.background} onSelect={() => {}} />);
  expect(screen.getByText(preset.label)).toBeInTheDocument();
  expect(screen.getByText('预设')).toBeInTheDocument();

  rerender(<CaseBackgroundPresetPicker value={`${preset.background}（补充：关注车辆轨迹）`} onSelect={() => {}} />);
  expect(screen.getByText('未使用预设，可手动输入')).toBeInTheDocument();
});

test('group tabs switch the visible preset cards', () => {
  render(<CaseBackgroundPresetPicker value="" onSelect={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: /选择预设背景/ }));

  // First group (涉网犯罪) does not contain the Android preset.
  expect(screen.queryByRole('button', { name: /手机取证（Android）/ })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: '专项检材' }));
  expect(screen.getByRole('button', { name: /手机取证（Android）/ })).toBeInTheDocument();
});

test('recommendation button is only offered when a callback is provided', () => {
  const preset = getPresetById('malware_infection');
  const onApply = vi.fn();

  const { rerender } = render(<CaseBackgroundPresetPicker value={preset.background} onSelect={() => {}} />);
  expect(screen.getByText(/建议筛选场景/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '套用到分析场景' })).not.toBeInTheDocument();

  rerender(<CaseBackgroundPresetPicker value={preset.background} onSelect={() => {}} onApplyRecommendation={onApply} />);
  fireEvent.click(screen.getByRole('button', { name: '套用到分析场景' }));
  expect(onApply).toHaveBeenCalledWith(preset);
});

test('field keeps the textarea usable while a preset is selected', () => {
  const preset = CASE_BACKGROUND_PRESETS[0];
  const onChange = vi.fn();
  render(<CaseBackgroundField value={preset.background} onChange={onChange} />);

  const textarea = screen.getByRole('textbox');
  expect(textarea).toHaveValue(preset.background);
  fireEvent.change(textarea, { target: { value: '自定义案情' } });
  expect(onChange).toHaveBeenCalledWith('自定义案情');
});

test('disabled picker cannot be opened', () => {
  render(<CaseBackgroundField value="" onChange={() => {}} disabled />);
  const toggle = screen.getByRole('button', { name: /选择预设背景/ });
  expect(toggle).toBeDisabled();
  fireEvent.click(toggle);
  expect(screen.queryByRole('button', { name: '专项检材' })).not.toBeInTheDocument();
});

test('picking a preset closes the panel', () => {
  const onChange = vi.fn();
  render(<CaseBackgroundField value="" onChange={onChange} />);
  fireEvent.click(screen.getByRole('button', { name: /选择预设背景/ }));
  fireEvent.click(screen.getByRole('button', { name: /电信网络诈骗/ }));
  expect(onChange).toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: '专项检材' })).not.toBeInTheDocument();
});
