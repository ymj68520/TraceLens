export const eventRunId = 'pg_' + 'e'.repeat(32);
export const eventPeopleId = 'pg_' + 'a'.repeat(32);
export const eventRun = (id = eventRunId, status = 'completed') => ({ run_id: id, task_id: 'T', status, progress: status === 'completed' ? 100 : 10, created_at: '2026-10-21T10:00:00Z', case_description: '核对付款线索' });
const events = [
  { id: 'event:e1', name: '付款安排', kind: 'event', provenance: { event_id: 'e1', version: 2 } },
  { id: 'event:e2', name: '后续收款', kind: 'event', provenance: { event_id: 'e2', version: 1 } },
  { id: 'event:e3', name: '孤立事件', kind: 'event', provenance: { event_id: 'e3', version: 1 } },
];
const material = { id: 'evidence:file:/材料/付款记录.txt', name: '付款记录.txt', kind: 'evidence' };
export const eventSource = { id: material.id, evidence_key: 'file:/材料/付款记录.txt', name: '付款记录.txt', kind: 'initial_analysis_summary', snapshot_hash: 's'.repeat(64), text_hash: 't'.repeat(64), text: '张三安排李四支付货款，需要核对收款情况。', payload: { initial_summary: '张三安排李四支付货款。', mtime: 100 } };
const person = { id: 'person:p1', name: '张三', kind: 'person', assessment: { priority: 'P1', core: true } };
const shared = { id: 'shared:s1', source: 'event:e1', target: 'event:e2', source_name: '付款安排', target_name: '后续收款', kind: 'shared_evidence', label: '共同关联材料', status: 'derived', source_ids: [material.id] };
const suggestion = { id: 'suggestion:s1', source: person.id, target: 'event:e1', source_name: '张三', target_name: '付款安排', kind: 'participation_candidate', label: '参与线索（待核）', status: 'machine_suggestion', reason: '材料记载付款安排，需核查人物身份和事件关系。', refs: [{ source_id: material.id, quote: '张三安排李四支付货款', snapshot_hash: eventSource.snapshot_hash, start: 0 }] };
export function eventGraphFixture(filters = {}, runId = '') {
  let nodes = [...events, material], links = [shared, { id: 'link:e1', source: 'event:e1', target: material.id, source_name: '付款安排', target_name: material.name, kind: 'event_evidence', label: 'LINKS_EVIDENCE', status: 'recorded' }];
  if (filters.view === 'associations') { nodes = [...events, person]; links = [suggestion]; }
  if (filters.view === 'evidence') links = links.filter(e => e.kind !== 'shared_evidence');
  if (filters.query) { nodes = nodes.filter(n => n.name.includes(filters.query)); links = []; }
  if (filters.relation_kind) links = links.filter(e => e.kind === filters.relation_kind);
  const items = [...nodes.map(n => ({ ...n, item_type: 'node' })), ...links.map(e => ({ ...e, item_type: 'link', name: e.label }))];
  return {
    nodes, links, items: items.slice(Number(filters.offset || 0), Number(filters.offset || 0) + Number(filters.limit || 25)), total_items: items.length,
    matched_nodes: nodes.length, matched_links: links.length, display_truncated: false, filters,
    source_version: 'f'.repeat(64), policy_version: 'event-graph:v1',
    available_events: events.map(e => ({ event_id: e.provenance.event_id, title: e.name, version: e.provenance.version })),
    coverage: { events_total: 3, events_captured: 3, evidence_total: 1, evidence_captured: 1, truncated: false, source_text_truncated: 0, source_payload_truncated: 0, time_policy: '文件时间不等于行为发生时间，不自动推断先后或因果。', deduplication: '准确事件标识与证据标识' },
    ...(runId ? { run: eventRun(runId), people_run_id: eventPeopleId, people_result_hash: 'p'.repeat(64), models: ['synthetic-model'], freshness: { investigation: 'unchanged', people_materials: 'unchanged' }, analysis_coverage: { selected_events: 3, events_not_selected: 0, candidate_pairs: 5, attempted_pairs: 2, omitted_pairs: 1, insufficient_source_pairs: 2, failed_pairs: 0, invalid_suggestions: 0, source_limited_pairs: 0, unverified_bindings: 0 } } : {}),
  };
}
export function eventDetailFixture(id, runId = '') {
  const target = [...events, material, person, shared, suggestion].find(n => n.id === id) || material;
  return { target, sources: id === 'event:e3' ? [] : [eventSource], source_version: 'f'.repeat(64), run_id: runId || null, relations: [], freshness: {} };
}
