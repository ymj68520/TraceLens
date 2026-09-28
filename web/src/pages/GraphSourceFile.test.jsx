import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';
import GraphSourceFile from './GraphSourceFile';
import { getGraphSourceFile } from '../services/graphitiService';

vi.mock('../services/graphitiService', () => ({ getGraphSourceFile: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

test('shows bounded real file preview separately from AI snapshot', async () => {
  getGraphSourceFile.mockResolvedValue({ source: {
    evidence_key: 'file:/case/a.txt', file_path: '/case/a.txt', source_image_available: false,
    original_preview: { available: true, kind: 'text', file_size: 13, recorded_size: 13,
      text: 'original text', copy_sha256: 'digest', integrity_note: '未比对原镜像' },
    snapshot: { initial_description: 'AI description' },
  } });
  render(<MemoryRouter initialEntries={['/graph-source-file?task_id=task-a&evidence_key=file%3A%2Fcase%2Fa.txt&relationship_id=edge-a']}>
    <Routes><Route path="/graph-source-file" element={<GraphSourceFile />} /></Routes>
  </MemoryRouter>);
  expect(await screen.findByTestId('source-file-preview')).toHaveTextContent('original text');
  expect(screen.getByText('AI description')).toBeInTheDocument();
  expect(screen.getByText(/原始镜像路径当前不可访问/)).toBeInTheDocument();
  expect(screen.getByText('← 返回知识图谱关系')).toHaveAttribute('href', '/knowledge-graph?task_id=task-a&relationship_id=edge-a');
  expect(getGraphSourceFile).toHaveBeenCalledWith('task-a', 'file:/case/a.txt');
});
