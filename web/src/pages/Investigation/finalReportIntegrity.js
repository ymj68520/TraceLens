const EXPECTED_SECTION_IDS = ['SEC-001', 'SEC-002', 'SEC-003', 'SEC-004', 'SEC-005'];

function duplicate(values) {
  const seen = new Set();
  const duplicates = [];
  values.forEach((value) => {
    if (seen.has(value) && !duplicates.includes(value)) duplicates.push(value);
    seen.add(value);
  });
  return duplicates;
}

export function checkFinalReportIntegrity(report) {
  const warnings = [];
  const sections = Array.isArray(report?.sections) ? report.sections : [];
  const sectionIds = sections.map((section) => section?.section_id);

  if (
    sectionIds.length !== EXPECTED_SECTION_IDS.length
    || sectionIds.some((id, index) => id !== EXPECTED_SECTION_IDS[index])
    || sections.some((section, index) => Number(section?.order) !== index + 1)
  ) {
    warnings.push({
      code: 'REPORT_SECTION_ORDER_INVALID',
      message: '已保存报告的章节与规定的五节结构不一致。',
    });
  }

  duplicate(sectionIds).forEach((sectionId) => {
    warnings.push({
      code: 'REPORT_DUPLICATE_SECTION',
      message: `已保存报告包含重复章节 ${sectionId}。`,
    });
  });

  const paragraphClaimIds = sections.flatMap((section) => (
    Array.isArray(section?.paragraphs)
      ? section.paragraphs.flatMap((paragraph) => paragraph?.claim_ids || [])
      : []
  ));
  const paragraphCitationIds = sections.flatMap((section) => (
    Array.isArray(section?.paragraphs)
      ? section.paragraphs.flatMap((paragraph) => paragraph?.citation_ids || [])
      : []
  ));
  const manifestClaimIds = Array.isArray(report?.claim_manifest)
    ? report.claim_manifest.map((claim) => claim?.claim_id)
    : [];
  const manifestCitationIds = Array.isArray(report?.citation_manifest)
    ? report.citation_manifest.map((citation) => citation?.citation_id)
    : [];

  const sameSet = (left, right) => {
    const leftSet = new Set(left);
    const rightSet = new Set(right);
    return leftSet.size === rightSet.size && [...leftSet].every((value) => rightSet.has(value));
  };

  if (!sameSet(paragraphClaimIds, manifestClaimIds)) {
    warnings.push({
      code: 'REPORT_CLAIM_MANIFEST_MISMATCH',
      message: '已保存的断言清单与正文中的断言引用不一致。',
    });
  }
  if (!sameSet(paragraphCitationIds, manifestCitationIds)) {
    warnings.push({
      code: 'REPORT_CITATION_MANIFEST_MISMATCH',
      message: '已保存的引用清单与正文中的证据引用不一致。',
    });
  }

  return warnings;
}
