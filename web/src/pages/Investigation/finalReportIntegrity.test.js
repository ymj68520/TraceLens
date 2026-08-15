import { expect, test } from 'vitest';
import { checkFinalReportIntegrity } from './finalReportIntegrity';

function report(overrides = {}) {
  return {
    sections: [1, 2, 3, 4, 5].map((order) => ({
      section_id: `SEC-00${order}`,
      order,
      paragraphs: order === 1 ? [{ text: 'text', claim_ids: ['claim-1'], citation_ids: ['CIT-001'] }] : [],
    })),
    claim_manifest: [{ claim_id: 'claim-1' }],
    citation_manifest: [{ citation_id: 'CIT-001' }],
    ...overrides,
  };
}

test('accepts an internally consistent persisted report', () => {
  expect(checkFinalReportIntegrity(report())).toEqual([]);
});

test('warns only for persisted section and manifest inconsistencies', () => {
  const warnings = checkFinalReportIntegrity(report({
    sections: [{ section_id: 'SEC-001', order: 2, paragraphs: [{ text: 'text', claim_ids: ['claim-x'], citation_ids: [] }] }],
    claim_manifest: [{ claim_id: 'claim-1' }],
    citation_manifest: [{ citation_id: 'CIT-001' }],
  }));
  expect(warnings.map((warning) => warning.code)).toEqual(expect.arrayContaining([
    'REPORT_SECTION_ORDER_INVALID',
    'REPORT_CLAIM_MANIFEST_MISMATCH',
    'REPORT_CITATION_MANIFEST_MISMATCH',
  ]));
});
