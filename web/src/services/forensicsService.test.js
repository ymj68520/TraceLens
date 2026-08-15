import { expect, test, vi } from 'vitest';
import { analyzeEventCluster, reanalyzeEventCluster } from './forensicsService';
import { pythonApi } from './api';

vi.mock('./api', () => ({
  default: { get: vi.fn() },
  pythonApi: { post: vi.fn() },
}));

test('forwards only the backend Timeline descriptor for cluster analysis', async () => {
  const descriptor = {
    bucket_index: 123,
    bucket_seconds: 300,
    event_type: 'MODIFIED',
    parent_directory: '/foo/',
    bucket_start_timestamp: 36900,
  };
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeEventCluster('task-a', { group_descriptor: descriptor, timestamp: 999999 });
  await reanalyzeEventCluster('task-a', { group_descriptor: descriptor, timestamp: 1 });

  expect(pythonApi.post).toHaveBeenNthCalledWith(1, '/api/llm/analyze-event-cluster', {
    task_id: 'task-a',
    group_descriptor: {
      bucket_index: 123,
      bucket_seconds: 300,
      event_type: 'MODIFIED',
      parent_directory: '/foo/',
    },
  });
  expect(pythonApi.post).toHaveBeenNthCalledWith(2, '/api/llm/analyze-event-cluster', {
    task_id: 'task-a',
    group_descriptor: {
      bucket_index: 123,
      bucket_seconds: 300,
      event_type: 'MODIFIED',
      parent_directory: '/foo/',
    },
    prompt: '请重新审视该事件簇，深度挖掘潜在威胁。',
  });
});

test('rejects cluster analysis without a backend descriptor', async () => {
  vi.clearAllMocks();
  await expect(analyzeEventCluster('task-a', { timestamp: 123 })).rejects.toThrow(
    'backend group descriptor is required'
  );
  expect(pythonApi.post).not.toHaveBeenCalled();
});
