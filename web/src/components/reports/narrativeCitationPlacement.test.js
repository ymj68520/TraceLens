import { expect, test } from 'vitest';
import { placeNarrativeCitations, explicitNarrativeParts } from './narrativeCitationPlacement';

test('explicit paragraph markers retain exact identity without filename guesses', () => {
  const citations = new Map([['c0001', { evidence_key: 'file:/one/History' }], ['c0002', { evidence_key: 'file:/two/History' }]]);
  expect(explicitNarrativeParts('观察甲[[c0001]]。观察乙[[c0002]]。', ['c0001', 'c0002'], citations))
    .toEqual([{ text: '观察甲' }, { citationId: 'c0001' }, { text: '。观察乙' }, { citationId: 'c0002' }, { text: '。' }]);
  expect(explicitNarrativeParts('未知[[foreign]]', ['c0001'], citations).map(p => p.text || '').join('')).toBe('未知〔引用待核对〕');
});

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
