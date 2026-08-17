import { describe, expect, test, vi } from 'vitest';
import { pollBatchStatus } from './llmService';

vi.mock('./api', () => ({
  pythonApi: { get: vi.fn() },
}));

import { pythonApi } from './api';

describe('pollBatchStatus cancellation and identity support', () => {
  test('aborts a pending poll without scheduling another request', async () => {
    const controller = new AbortController();
    let rejectRequest;
    pythonApi.get.mockReturnValueOnce(new Promise((_, reject) => {
      rejectRequest = reject;
    }));

    const pending = pollBatchStatus('job-a', vi.fn(), 1, { signal: controller.signal });
    controller.abort();
    rejectRequest(new Error('transport should be ignored after abort'));

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(pythonApi.get).toHaveBeenCalledTimes(1);
  });

  test('stops after terminal completion', async () => {
    pythonApi.get.mockReset();
    pythonApi.get.mockResolvedValueOnce({ status: 'completed', results: [] });
    const onProgress = vi.fn();

    await expect(pollBatchStatus('job-a', onProgress, 1)).resolves.toMatchObject({
      status: 'completed',
    });
    expect(onProgress).toHaveBeenCalledWith({ status: 'completed', results: [] });
    expect(pythonApi.get).toHaveBeenCalledTimes(1);
  });
});
