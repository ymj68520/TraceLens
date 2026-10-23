import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import AnalystNoteEditor from './AnalystNoteEditor';
import { saveAnalystNote } from '../../../services/investigationService';

vi.mock('../../../services/investigationService', () => ({ saveAnalystNote: vi.fn() }));

test('failed save shows the error and preserves the note for retry', async () => {
  saveAnalystNote.mockRejectedValueOnce(new Error('保存失败'));
  const saved = vi.fn();
  render(<AnalystNoteEditor taskId="T" evidenceKey="file:/a" onSaved={saved} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '核对文件来源' } });
  fireEvent.click(screen.getByRole('button', { name: '保存备注' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('保存失败');
  expect(screen.getByRole('textbox')).toHaveValue('核对文件来源');
  expect(saved).not.toHaveBeenCalled();
  saveAnalystNote.mockResolvedValueOnce({ note: { content: '核对文件来源', version: 1 } });
  fireEvent.click(screen.getByRole('button', { name: '保存备注' }));
  await vi.waitFor(() => expect(saved).toHaveBeenCalledWith({ content: '核对文件来源', version: 1 }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
