import { expect, test } from 'vitest';
import { FixtureReportDataSource } from './reportDataSource';

const fixture = {
  versions: [{ report_id: 'r1', version: 1, status: 'ready' }],
  manifests: { r1: { report_id: 'r1', title: 'Fixture', categories: [] } },
  pages: { 'r1:android.sms:1': { page: 1, records: [{ record_id: 'rec_1' }] } },
  searches: { 'r1:验证码': { total: 1, hits: [{ record_id: 'rec_1' }] } },
};

test('fixture and HTTP sources share the same asynchronous contract', async () => {
  const source = new FixtureReportDataSource(fixture);

  expect(await source.listVersions('task', 't1')).toEqual(fixture.versions);
  expect(await source.getManifest('r1')).toEqual(fixture.manifests.r1);
  expect(await source.getCategoryPage('r1', 'android.sms', 1)).toEqual(
    fixture.pages['r1:android.sms:1'],
  );
  expect((await source.search('r1', '验证码')).total).toBe(1);
});
