import { expect, test, vi } from 'vitest';
import {
  analyzeEventCluster,
  reanalyzeEventCluster,
  estimateEventClusterAnalysis,
  runEventClusterAnalysis,
  getEventClusterRunStatus,
  getEventClusterAnalyses,
} from './forensicsService';
import { pythonApi } from './api';

vi.mock('./api', () => ({
  default: { get: vi.fn() },
  pythonApi: { get: vi.fn(), post: vi.fn() },
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
    trigger: 'timeline_manual',
    prompt: '请重新审视该事件簇，深度挖掘潜在威胁。',
  });
});

test('forwards the auto-analysis trigger from the Timeline auto-analyze effect', async () => {
  vi.clearAllMocks();
  const descriptor = {
    bucket_index: 5,
    bucket_seconds: 60,
    event_type: 'CREATED',
    parent_directory: '/tmp/',
  };
  pythonApi.post.mockResolvedValue({ success: true });

  await analyzeEventCluster('task-b', { group_descriptor: descriptor }, { trigger: 'timeline_auto' });

  expect(pythonApi.post).toHaveBeenCalledWith('/api/llm/analyze-event-cluster', {
    task_id: 'task-b',
    group_descriptor: {
      bucket_index: 5,
      bucket_seconds: 60,
      event_type: 'CREATED',
      parent_directory: '/tmp/',
    },
    trigger: 'timeline_auto',
  });
});

test('rejects cluster analysis without a backend descriptor', async () => {
  vi.clearAllMocks();
  await expect(analyzeEventCluster('task-a', { timestamp: 123 })).rejects.toThrow(
    'backend group descriptor is required'
  );
  expect(pythonApi.post).not.toHaveBeenCalled();
});

test('run wrappers post task id and optional window, query job by id', async () => {
  vi.clearAllMocks();
  pythonApi.post.mockResolvedValue({ success: true });
  pythonApi.get.mockResolvedValue({ status: 'completed' });

  await estimateEventClusterAnalysis('task-a');
  await runEventClusterAnalysis('task-a');
  await runEventClusterAnalysis('task-a', 3600);
  await getEventClusterRunStatus('job-1');
  await getEventClusterAnalyses('task-a', { bucket_seconds: 60, latest_only: 'true' });

  expect(pythonApi.post).toHaveBeenNthCalledWith(1, '/api/llm/event-cluster-analysis/estimate', {
    task_id: 'task-a',
  });
  expect(pythonApi.post).toHaveBeenNthCalledWith(2, '/api/llm/event-cluster-analysis/run', {
    task_id: 'task-a',
  });
  expect(pythonApi.post).toHaveBeenNthCalledWith(3, '/api/llm/event-cluster-analysis/run', {
    task_id: 'task-a',
    bucket_seconds: 3600,
  });
  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/llm/event-cluster-analysis/run/job-1');
  expect(pythonApi.get).toHaveBeenNthCalledWith(2, '/api/llm/event-cluster-analyses', {
    params: { task_id: 'task-a', bucket_seconds: 60, latest_only: 'true' },
  });
});
