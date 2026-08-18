import { beforeEach, expect, test, vi } from 'vitest';
import { getExtensionStats, getStorageClassStats } from './ossService';
import api from './api';

vi.mock('./api', () => ({
  default: {
    get: vi.fn(),
  },
}));

beforeEach(() => vi.clearAllMocks());

test('uses mounted C++ OSS statistics route names', async () => {
  api.get.mockResolvedValue({});

  await getStorageClassStats('task-1');
  await getExtensionStats('task-1');

  expect(api.get).toHaveBeenNthCalledWith(1, '/api/forensics/oss/stats/storage-class', {
    params: { task_id: 'task-1' },
  });
  expect(api.get).toHaveBeenNthCalledWith(2, '/api/forensics/oss/stats/extensions', {
    params: { task_id: 'task-1' },
  });
});
