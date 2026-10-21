export const peopleRunId = 'pg_' + '1'.repeat(32);
export const peopleRun = (id = peopleRunId, status = 'completed') => ({
  run_id: id, task_id: 'T', status, phase: status === 'running' ? 'discovering_people' : 'completed',
  progress: status === 'running' ? 40 : 100, created_at: '2026-10-20T12:00:00Z',
  actor: 'synthetic-analyst', operation: 'discover', input_hash: 'a'.repeat(64), result_hash: 'b'.repeat(64),
  case_description: '合成案情：核查付款安排。', policy_version: 'people-graph:v1',
});
export const peopleAssessment = (priority = 'unassessed', core = false) => ({
  priority, core, reason: priority === 'unassessed' ? '尚未评估或依据不足' : '材料记载付款安排，需要核查。',
  refs: priority === 'unassessed' ? [] : [{ source_id: 'm1', quote: '张三安排李四付款。', basis_type: 'text', start: 0, end: 9 }],
  relations: priority === 'unassessed' ? [] : [{ question_id: 'q001', relation: priority === 'P3' ? 'background' : 'supports' }],
  status: priority === 'unassessed' ? 'unassessed' : 'assessed', review_status: 'machine_suggested',
});

export function peopleGraphFixture(filters = {}, id = peopleRunId, taskId = 'T') {
  const basePeople = [
    { id: 'p1', name: '张三', names: ['张三'], identity_status: 'recorded_identifier', mention_ids: ['m01', 'm02'], relation_count: 1, assessment: peopleAssessment('P1', true) },
    { id: 'p2', name: '李四', names: ['李四'], identity_status: 'candidate', mention_ids: ['m03'], relation_count: 1, assessment: peopleAssessment('P2') },
    { id: 'p3', name: '王五', names: ['王五'], identity_status: 'candidate', mention_ids: ['m04'], relation_count: 0, assessment: peopleAssessment('P3') },
    { id: 'p4', name: '张三（待区分）', names: ['张三'], identity_status: 'ambiguous', mention_ids: ['m05'], relation_count: 0, assessment: peopleAssessment() },
  ].map(p => ({ ...p, kind: 'person', mention_count: p.mention_ids.length, material_ids: ['m1'],
    same_name_candidates: p.id === 'p4' ? ['p1'] : [] }));
  const edge = { id: 'r1', source: 'p1', target: 'p2', label: '安排付款', kind: 'direct', assessment: peopleAssessment('P1') };
  let nodes = basePeople;
  if (filters.priority === 'core') nodes = nodes.filter(p => p.assessment.core);
  else if (filters.priority === 'P1_P2') nodes = nodes.filter(p => ['P1', 'P2'].includes(p.assessment.priority));
  else if (filters.priority && filters.priority !== 'all') nodes = nodes.filter(p => p.assessment.priority === filters.priority);
  if (filters.query) nodes = nodes.filter(p => p.names.some(n => n.includes(filters.query)));
  if (filters.identity_status === 'isolated') nodes = nodes.filter(p => !p.relation_count);
  if (filters.identity_status === 'ambiguous') nodes = nodes.filter(p => p.same_name_candidates.length);
  if (filters.focus_id) nodes = nodes.filter(p => [filters.focus_id, 'p1', 'p2'].includes(p.id));
  let links = nodes.some(p => p.id === 'p1') && nodes.some(p => p.id === 'p2') ? [edge] : [];
  const total = nodes.length;
  if (filters.include_context && nodes.length === 1 && nodes[0].id === 'p1') {
    nodes = [...nodes, { ...basePeople[1], context_only: true }];
    links = [{ ...edge, context_only: true }];
  }
  if (filters.view === 'relations') {
    nodes = basePeople.slice(0, 2).map(p => ({ ...p, kind: 'entity', assessment: peopleAssessment() }));
    links = [{ ...edge, source_name: '张三', target_name: '李四', fact: '来源中的付款安排', episode_ids: ['e1'] }];
  }
  return {
    run: { ...peopleRun(id), task_id: taskId }, nodes, links,
    items: filters.view === 'relations' ? links : nodes.filter(p => !p.context_only),
    total_items: filters.view === 'relations' ? 1 : total, matched_nodes: nodes.length, matched_relations: links.length,
    display_truncated: false, policy_version: 'people-graph:v1', models: ['synthetic-model'],
    freshness: { materials_changed: false, task_case_changed: false, graph_state: 'unchanged' },
    coverage: { registered_files: 3, complete_files: 1, partial_files: 1, unavailable_files: 1,
      unprocessed_files: 0, identified_mentions: 5, people: 4, ambiguous_people: 1, person_relations: 1 },
    graph_coverage: { available: true, captured_relations: 2, total_relations: 3, unread_or_missing_episodes: 1, episode_text_truncated: 1 },
    assessment_coverage: { attempted: 5, pending: 1, truncated: false },
    discovery_coverage: { chunks_attempted: 3, chunks_failed: 1 },
    questions: [{ question_id: 'q001', text: '核查付款安排', origin: 'case' }],
    relation_labels: ['安排付款'],
    materials: [{ id: 'm1', path: '/合成/往来记录.txt', kind: 'text', status: 'complete', limitations: [],
      original_characters: 30, processed_characters: 30, source_hash: 'c'.repeat(64) }],
    identity_history: [],
  };
}

export function peopleDetailFixture(targetId = 'p1') {
  const graph = peopleGraphFixture();
  const person = graph.nodes.find(p => p.id === targetId);
  const target = person || graph.links[0];
  return {
    target, assessment: target.assessment, freshness: graph.freshness, run_id: peopleRunId,
    mentions: person ? person.mention_ids.map((id, i) => ({ id, name: person.names[0], material_id: 'm1',
      ref: { source_id: 'm1', quote: '张三安排李四付款。', start: i * 10, end: i * 10 + 9, ambiguous: false },
      identity_number: '', identity_quote: '' })) : [],
    refs: [{ source_id: 'm1', quote: '张三安排李四付款。', basis_type: 'text' }],
    sources: [{ id: 'm1', path: '/合成/往来记录.txt', evidence_key: 'file:/合成/往来记录.txt',
      kind: 'text', text: '张三安排李四付款。\n<img src=x onerror="window.__injected=true">', source_hash: 'c'.repeat(64), preview_truncated: false }],
    relations: [],
  };
}
