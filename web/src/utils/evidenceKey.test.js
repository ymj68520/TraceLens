import { expect, test } from 'vitest';
import { investigationFileUrl, investigationEvidenceUrl, reportCitationUrl } from './evidenceKey';
import { fileEvidenceKey, fileSourceReference, stripFileKeyPrefix } from './evidenceKey';

test('同路径不同来源的证据引用和回链保持独立，显示原始中文路径', () => {
  const a = { path: '/资料/原始 文件(1).txt', source_id: 'a'.repeat(64) };
  const b = { ...a, source_id: 'b'.repeat(64) };
  const key = fileEvidenceKey(a);
  expect(key).not.toBe(fileEvidenceKey(b));
  expect(fileSourceReference(a)).not.toBe(fileSourceReference(b));
  expect(stripFileKeyPrefix(key)).toBe(a.path);
  const url = new URL(investigationFileUrl('t', key), 'http://localhost');
  expect(url.searchParams.get('file')).toBe(a.path);
  expect(url.searchParams.get('evidence_key')).toBe(key);
  expect(stripFileKeyPrefix(`file:v2:${a.source_id}:%ZZ`)).toBeNull();
});

test('citation links preserve the exact task, report version, file, and citation id', () => {
  expect(investigationFileUrl('task-1', 'file:/case/a file.txt', { reportId: 'rep-2', citationId: 'c001' }))
    .toBe('/investigation?task_id=task-1&file=%2Fcase%2Fa%20file.txt&report_id=rep-2&citation_id=c001');
  expect(reportCitationUrl('task-1', 'rep-2', 'c001'))
    .toBe('/case-intelligence?task_id=task-1&tab=forensic&report_id=rep-2&citation_id=c001');
  expect(investigationFileUrl('task-1', 'cluster:v1:100:MODIFIED')).toBeNull();
});

test('Android report citation deep-link preserves exact frozen key and task', () => {
  const key = `android_artifact:v1:task-1:${'a'.repeat(64)}:sms:7`;
  expect(investigationEvidenceUrl('task-1', key, { reportId: 'r2', citationId: 'c001' }))
    .toBe(`/investigation?task_id=task-1&evidence_key=${encodeURIComponent(key)}&report_id=r2&citation_id=c001`);
  expect(investigationEvidenceUrl('other', key)).toBeNull();
  expect(investigationEvidenceUrl('task-1', 'cluster:v1:1:x')).toBeNull();
});
