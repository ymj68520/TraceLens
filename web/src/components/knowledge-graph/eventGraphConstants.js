export const eventKinds = { event: '调查事件', evidence: '证据材料', person: '人员', analysis: '分析版本', claim: '分析结论' };
export const edgeNames = { event_evidence: '关联材料', analysis_evidence: '分析材料', analysis_claim: '包含结论', claim_evidence: '引用材料', shared_evidence: '共同关联材料', mentioned_in: '材料中提及', participation_candidate: '参与线索（待核）', related_candidate: '事件关联（待核）', inconsistent_candidate: '事件差异（待核）' };
export const edgeLabel = edge => edge.kind === 'mentioned_in' && edge.binding_verified === false ? '关联材料有提及（版本待核）' : edgeNames[edge.kind] || edge.label;
