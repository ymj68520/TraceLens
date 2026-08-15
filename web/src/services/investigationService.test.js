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

  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/investigation/task%2Fa/final-reports');
  expect(pythonApi.get).toHaveBeenNthCalledWith(2, '/api/investigation/task%2Fa/final-reports/report%20id');
  expect(pythonApi.get).toHaveBeenNthCalledWith(3, '/api/investigation/task%2Fa/claims/claim%2Fid');
});

test('uses encoded task and report IDs for presentation endpoints', async () => {
  vi.clearAllMocks();
  await getFinalReportMarkdown('task/a', 'report id');
  await getFinalReportHtml('task/a', 'report id');
  await getFinalReportPrint('task/a', 'report id');

  expect(pythonApi.get).toHaveBeenNthCalledWith(1, '/api/investigation/task%2Fa/final-reports/report%20id/markdown');
  expect(pythonApi.get).toHaveBeenNthCalledWith(2, '/api/investigation/task%2Fa/final-reports/report%20id/html');
  expect(pythonApi.get).toHaveBeenNthCalledWith(3, '/api/investigation/task%2Fa/final-reports/report%20id/print');
});

test('uses encoded task and report IDs for publication read and publish endpoints', async () => {
  await getFinalReportPublication('task/a', 'report id');
  await publishFinalReport('task/a', 'report id');

  expect(pythonApi.get).toHaveBeenCalledWith('/api/investigation/task%2Fa/final-reports/report%20id/publication');
  expect(pythonApi.post).toHaveBeenCalledWith('/api/investigation/task%2Fa/final-reports/report%20id/publish');
});
