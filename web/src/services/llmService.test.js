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
    file_path: '/tmp/test.dll',
    files_db_path: '/tmp/files.db',
    prompt: null,
  });
});
