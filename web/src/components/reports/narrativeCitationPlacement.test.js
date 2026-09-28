import { expect, test } from 'vitest';
import { placeNarrativeCitations } from './narrativeCitationPlacement';

test('places manifest citations after unique literal filenames or stems', () => {
  const content = '检材含“第一天基本信息”材料与聊天话术1.docx。';
  const citations = new Map([
    ['c001', { evidence_key: 'file:/case/第一天基本信息.docx' }],
    ['c002', { evidence_key: 'file:/case/聊天话术1.docx' }],
  ]);
  const { placements, unresolved } = placeNarrativeCitations(content, ['c001', 'c002'], citations);

  expect(placements.map((item) => item.citationId)).toEqual(['c001', 'c002']);
  expect(content.slice(0, placements[0].end)).toMatch(/第一天基本信息$/);
  expect(content.slice(0, placements[1].end)).toMatch(/聊天话术1\.docx$/);
  expect(unresolved).toEqual([]);
});

test('does not guess a sentence for repeated or absent evidence names', () => {
  const citations = new Map([
    ['c001', { evidence_key: 'file:/case/audit.log' }],
    ['c002', { evidence_key: 'file:/case/unmentioned.pdf' }],
  ]);
  const result = placeNarrativeCitations('audit.log 以及 audit.log 均存在。', ['c001', 'c002', 'ghost'], citations);

  expect(result.placements).toEqual([]);
  expect(result.unresolved).toEqual(['c001', 'c002', 'ghost']);
});
