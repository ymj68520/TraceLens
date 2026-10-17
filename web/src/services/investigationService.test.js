import { expect, test, vi } from 'vitest';
import {
  getClaimProvenance,
  getFinalReport,
  getFinalReportHtml,
  getFinalReportMarkdown,
  getFinalReportPrint,
  getFinalReportPublication,
  getFinalReports,
  publishFinalReport,
} from './investigationService';
import { pythonApi } from './api';

vi.mock('./api', () => ({
  pythonApi: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

test('uses encoded task and report IDs for read-only final report endpoints', async () => {
  pythonApi.get.mockResolvedValueOnce({ reports: [] }).mockResolvedValueOnce({ report: null });

  await getFinalReports('task/a');
  await getFinalReport('task/a', 'report id');
  await getClaimProvenance('task/a', 'claim/id');

  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/investigation/workbench/task%2Fa/final-reports');
  expect(pythonApi.get).toHaveBeenNthCalledWith(2, '/api/investigation/workbench/task%2Fa/final-reports/report%20id');
  expect(pythonApi.get).toHaveBeenNthCalledWith(3, '/api/investigation/workbench/task%2Fa/claims/claim%2Fid');
});

test('uses encoded task and report IDs for presentation endpoints', async () => {
  vi.clearAllMocks();
  await getFinalReportMarkdown('task/a', 'report id');
  await getFinalReportHtml('task/a', 'report id');
  await getFinalReportPrint('task/a', 'report id');

  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/investigation/workbench/task%2Fa/final-reports/report%20id/markdown', { responseType: 'text' });
  expect(pythonApi.get).toHaveBeenNthCalledWith(2, '/api/investigation/workbench/task%2Fa/final-reports/report%20id/html', { responseType: 'text' });
  expect(pythonApi.get).toHaveBeenNthCalledWith(3, '/api/investigation/workbench/task%2Fa/final-reports/report%20id/print', { responseType: 'text' });
});

test('uses encoded task and report IDs for publication read and publish endpoints', async () => {
  await getFinalReportPublication('task/a', 'report id');
  await publishFinalReport('task/a', 'report id');

  expect(pythonApi.get).toHaveBeenCalledWith('/api/investigation/workbench/task%2Fa/final-reports/report%20id/publication');
  expect(pythonApi.post).toHaveBeenCalledWith('/api/investigation/workbench/task%2Fa/final-reports/report%20id/publish');
});

test('handles agent review read endpoints with task_id and candidate_id encoding', async () => {
  const {
    listAgentReviewCandidates,
    getAgentReviewCandidate,
    getAgentReviewHistory,
    submitAgentReviewDecision,
  } = await import('./investigationService');

  vi.clearAllMocks();
  pythonApi.get.mockResolvedValueOnce({ candidates: [] })
    .mockResolvedValueOnce({ candidate_id: 'finding:disp_1' })
    .mockResolvedValueOnce({ history: [] });
  pythonApi.post.mockResolvedValueOnce({ review_id: 'rev_123', status: 'accepted' });

  await listAgentReviewCandidates('task-001', 'inv-001');
  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/investigation/agent/review-candidates', {
    params: { task_id: 'task-001', investigation_id: 'inv-001' },
  });

  await getAgentReviewCandidate('task-001', 'finding:disp_test/01', 'inv-001');
  expect(pythonApi.get).toHaveBeenNthCalledWith(
    2,
    '/api/investigation/agent/review-candidates/finding%3Adisp_test%2F01',
    { params: { task_id: 'task-001', investigation_id: 'inv-001' } },
  );

  await getAgentReviewHistory('task-001', 'finding:disp_test/01', 'inv-001');
  expect(pythonApi.get).toHaveBeenNthCalledWith(3, '/api/investigation/agent/reviews/history', {
    params: { task_id: 'task-001', candidate_id: 'finding:disp_test/01', investigation_id: 'inv-001' },
  });

  const payload = {
    task_id: 'task-001',
    review_target_id: 'finding:disp_test/01',
    expected_source_revision: 1,
    expected_candidate_hash: 'hash123',
    decision: 'accepted',
    reviewer: 'analyst',
    request_id: 'req_123',
  };
  await submitAgentReviewDecision(payload);
  expect(pythonApi.post).toHaveBeenCalledWith('/api/investigation/agent/review', payload);
});
