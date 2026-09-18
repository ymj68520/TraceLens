import { beforeEach, expect, test, vi } from 'vitest';
import { analyzeDLL } from './llmService';
import { pythonApi } from './api';

vi.mock('./api', () => ({ pythonApi: { post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

test('DLL analysis uses the Python LLM service client', async () => {
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeDLL({
    filePath: '/tmp/test.dll',
    filesDbPath: '/tmp/files.db',
  });

  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze/dll', {
    task_id: null,
    file_path: '/tmp/test.dll',
    files_db_path: '/tmp/files.db',
    prompt: null,
  });
});

test('DLL analysis forwards taskId so results persist to the task database', async () => {
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeDLL({
    taskId: '2bab5e0f-b5da-40b9-8336-db3f1c5583da',
    filePath: '/pagefile.sys',
    filesDbPath: '/tmp/files.db',
  });

  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze/dll', {
    task_id: '2bab5e0f-b5da-40b9-8336-db3f1c5583da',
    file_path: '/pagefile.sys',
    files_db_path: '/tmp/files.db',
    prompt: null,
  });
});
