import { beforeEach, expect, test, vi } from 'vitest';
import { analyzeDLL, analyzeContent } from './llmService';
import { pythonApi } from './api';

vi.mock('./api', () => ({ pythonApi: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

test('DLL analysis uses the Python LLM service client', async () => {
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeDLL({
    taskId: 'task-1',
    filePath: '/tmp/test.dll',
    filesDbPath: '/tmp/files.db',
  });

  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze/dll', {
    task_id: 'task-1',
    file_path: '/tmp/test.dll',
    files_db_path: '/tmp/files.db',
    prompt: null,
  });
});

test('DLL analysis without a task sends a null task anchor', async () => {
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeDLL({ filePath: '/tmp/test.dll' });

  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze/dll', {
    task_id: null,
    file_path: '/tmp/test.dll',
    files_db_path: null,
    prompt: null,
  });
});

test('content analysis carries the task anchor for persistence', async () => {
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeContent({
    taskId: 'task-2',
    filePath: '/evidence/a.docx',
    filesDbPath: '/data/tasks/task-2/x_files.db',
  });

  expect(pythonApi.post).toHaveBeenCalledWith(
    '/api/llm/analyze',
    expect.objectContaining({
      task_id: 'task-2',
      file_path: '/evidence/a.docx',
      files_db_path: '/data/tasks/task-2/x_files.db',
    }),
  );
});
