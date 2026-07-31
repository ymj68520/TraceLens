import { beforeEach, expect, test, vi } from 'vitest';
import { pythonApi } from './api';
import { HttpReportDataSource } from './reportDataSource';

vi.mock('./api', () => ({ pythonApi: { get: vi.fn(), post: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

test('HTTP source encodes category and search parameters', async () => {
  pythonApi.get.mockResolvedValue({ records: [] });
  const source = new HttpReportDataSource(pythonApi);

  await source.getCategoryPage('r1', 'android.wechat/messages', 2);
  await source.search('r1', '手机号 / hash', { offset: 4, limit: 20 });

  expect(pythonApi.get).toHaveBeenNthCalledWith(
    1,
    '/api/reports/r1/categories/android.wechat%2Fmessages/pages/2',
  );
  expect(pythonApi.get).toHaveBeenNthCalledWith(
    2,
    '/api/reports/r1/search',
    { params: { q: '手机号 / hash', offset: 4, limit: 20 } },
  );
});
