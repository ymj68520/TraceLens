import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import PeopleGraphCanvas from './PeopleGraphCanvas';
import { PEOPLE_LEVELS, IDENTITY_LABELS, peopleStyle, peopleLimitLabel, peopleBasisLabel } from './peopleGraphStyles';
import { fetchTaskById } from '../../services/taskService';
import * as api from '../../services/peopleGraphService';

const field = 'rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100';
const button = 'rounded-lg border border-blue-200 px-3 py-2 text-sm text-blue-800 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-800 dark:text-blue-200 dark:hover:bg-blue-950';
const defaults = { priority: 'all', question_id: '', relation_kind: '', relation_label: '', material_id: '', query: '',
  identity_status: 'all', focus_id: '', include_context: false, max_nodes: 200, offset: 0, limit: 50 };
const statusLabel = { running: '运行中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '服务重启中断' };
const phases = { queued: '等待处理', reading_materials: '读取登记材料', discovering_people: '识别人物提及与关系', assessing_priorities: '评估案情优先级' };
const message = error => typeof error?.data?.detail === 'string' ? error.data.detail : error?.message || '操作暂不可用';

function Badge({ assessment }) {
  const style = peopleStyle(assessment);
  return <span className="inline-flex rounded-md border px-2 py-1 text-xs font-semibold" style={{ color: style.color, borderColor: style.color }}
    data-priority={assessment?.priority || 'unassessed'}>{style.label}</span>;
}

export default function PeopleGraphPanel({ taskId, view = 'people', initialRunId = '', onRunChange,
  service = api, taskLoader = fetchTaskById, pollMs = 2000, Canvas = PeopleGraphCanvas }) {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(initialRunId);
  const [data, setData] = useState(null);
  const [filters, setFilters] = useState(defaults);
  const [context, setContext] = useState('');
  const [actor, setActor] = useState('');
  const [fileLimit, setFileLimit] = useState(200);
  const [graphLimit, setGraphLimit] = useState(500);
  const [assessmentLimit, setAssessmentLimit] = useState(100);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [detail, setDetail] = useState(null);
  const [detailId, setDetailId] = useState('');
  const [detailError, setDetailError] = useState(null);
  const [selected, setSelected] = useState([]);
  const [selectedMentions, setSelectedMentions] = useState([]);
  const [reason, setReason] = useState('');
  const [displayName, setDisplayName] = useState('');
  const edited = useRef(false);
  const scopeRef = useRef(taskId);
  const scopeInitialRef = useRef({ taskId, runId: initialRunId });
  if (scopeInitialRef.current.taskId !== taskId) scopeInitialRef.current = { taskId, runId: initialRunId };
  const navigationRef = useRef(0);
  const selectionRef = useRef(runId);
  scopeRef.current = taskId;
  selectionRef.current = runId;
  const listRequest = useRef(0);
  const graphRequest = useRef(0);
  const detailRequest = useRef(0);
  const submitRequest = useRef(null);
  const dataIdentity = useRef('');
  const dialogRef = useRef(null);
  const selectedRun = runs.find(r => r.run_id === runId);
  const active = runs.find(r => r.status === 'running');
  const filtersKey = JSON.stringify({ ...filters, view });
  const queryIdentity = `${taskId}|${runId}|${filtersKey}`;
  const queryIdentityRef = useRef(queryIdentity);
  queryIdentityRef.current = queryIdentity;

  const refreshRuns = useCallback(async (preferId = null) => {
    const request = ++listRequest.current;
    const navigation = navigationRef.current;
    const result = await service.listPeopleRuns(taskId);
    if (request !== listRequest.current || scopeRef.current !== taskId) return;
    setRuns(result.runs || []);
    setRunId(current => (navigationRef.current === navigation ? preferId : null)
      || current || result.runs?.find(r => r.status === 'completed')?.run_id || result.runs?.[0]?.run_id || '');
  }, [service, taskId]);

  useEffect(() => {
    const list = listRequest, graphs = graphRequest, details = detailRequest;
    navigationRef.current++;
    setRuns([]); setRunId(scopeInitialRef.current.runId); setData(null); setFilters(defaults); setError(null);
    setDetail(null); setDetailId(''); setSelected([]); setSelectedMentions([]);
    setContext(''); edited.current = false; submitRequest.current = null; setSubmitting(false);
    let active = true;
    if (taskId) {
      refreshRuns().catch(err => { if (active) setError(err); });
      taskLoader(taskId).then(task => { if (active && !edited.current) setContext(task?.case_description || ''); }).catch(() => {});
    }
    const submissions = submitRequest;
    return () => { active = false; list.current++; graphs.current++; details.current++; submissions.current = null; };
  }, [taskId, refreshRuns, taskLoader]);

  useEffect(() => { if (runId) onRunChange?.(runId); }, [runId, onRunChange]);

  useEffect(() => {
    if (!active?.run_id) return undefined;
    let alive = true;
    let timer;
    const poll = async () => {
      try {
        const next = await service.getPeopleRun(taskId, active.run_id);
        if (!alive) return;
        setRuns(values => values.map(row => row.run_id === next.run_id ? { ...row, ...next } : row));
        if (next.status !== 'running') { await refreshRuns(); return; }
      } catch (err) { if (alive) setError(err); }
      if (alive) timer = setTimeout(poll, pollMs);
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [active?.run_id, service, taskId, pollMs, refreshRuns]);

  useEffect(() => {
    const graphs = graphRequest;
    const request = ++graphs.current;
    setDetailId(''); setDetail(null); setLoading(false);
    if (!taskId || !runId || selectedRun?.status !== 'completed') { setData(null); return undefined; }
    const identity = queryIdentity;
    setLoading(true);
    service.getPeopleGraph(taskId, runId, JSON.parse(filtersKey)).then(result => {
      if (request !== graphs.current || queryIdentityRef.current !== identity) return;
      dataIdentity.current = identity;
      setData(result); setError(null);
      if (!edited.current) setContext(result.run.case_description || '');
    }).catch(err => { if (request === graphs.current && queryIdentityRef.current === identity) setError(err); })
      .finally(() => { if (request === graphs.current && queryIdentityRef.current === identity) setLoading(false); });
    return () => { graphs.current++; };
  }, [taskId, runId, selectedRun?.status, service, filtersKey, queryIdentity, refreshToken]);

  useEffect(() => { setSelected([]); setSelectedMentions([]); setReason(''); setDisplayName(''); }, [taskId, runId, view]);

  const close = () => { detailRequest.current++; setDetailId(''); setDetail(null); setDetailError(null); setSelectedMentions([]); };
  const openDetail = async id => {
    const request = ++detailRequest.current;
    const identity = queryIdentity;
    setDetailId(id); setDetail(null); setDetailError(null); setSelectedMentions([]);
    try {
      const result = await service.getPeopleTarget(taskId, runId, id);
      if (request === detailRequest.current && queryIdentityRef.current === identity) setDetail(result);
    } catch (err) { if (request === detailRequest.current && queryIdentityRef.current === identity) setDetailError(err); }
  };
  const dialogOpen = Boolean(detailId);
  useEffect(() => {
    if (!dialogOpen) return undefined;
    const previous = document.activeElement;
    dialogRef.current?.focus();
    const key = event => {
      if (event.key === 'Escape') close();
      if (event.key !== 'Tab') return;
      const dialog = dialogRef.current;
      const controls = [...(dialog?.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled)') || [])].filter(e => e.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (!first || document.activeElement === dialog || !dialog.contains(document.activeElement)
        || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
        event.preventDefault(); (event.shiftKey ? last : first)?.focus();
      }
    };
    window.addEventListener('keydown', key);
    return () => { window.removeEventListener('keydown', key); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, [dialogOpen]);

  const launch = async mode => {
    if (submitRequest.current || active || !actor.trim() || context.length > 8000) return;
    const request = {}; submitRequest.current = request;
    const selectedAtClick = runId;
    const navigation = navigationRef.current;
    setSubmitting(true); setError(null);
    try {
      const next = await service.startPeopleRun({ task_id: taskId, mode, requested_by: actor.trim(),
        case_description: context, max_files: fileLimit, max_graph_relations: graphLimit, max_assessments: assessmentLimit,
        ...(selectedRun?.status === 'completed' ? { base_run_id: runId } : {}) });
      if (scopeRef.current !== taskId || submitRequest.current !== request) return;
      await refreshRuns(selectionRef.current === selectedAtClick && navigationRef.current === navigation ? next.run_id : null);
    } catch (err) { if (scopeRef.current === taskId && submitRequest.current === request) setError(err); }
    finally { if (submitRequest.current === request) { submitRequest.current = null; setSubmitting(false); } }
  };
  const revise = async operation => {
    if (submitRequest.current || !actor.trim() || !reason.trim() || active) return;
    const request = {}; submitRequest.current = request; setSubmitting(true); setError(null);
    const navigation = navigationRef.current;
    try {
      const next = await service.reviewPeopleIdentity(taskId, runId, { operation,
        person_ids: operation === 'merge' ? selected : [detailId], mention_ids: operation === 'split' ? selectedMentions : [],
        display_name: displayName, reason: reason.trim(), reviewer: actor.trim() });
      if (scopeRef.current !== taskId || submitRequest.current !== request) return;
      if (navigationRef.current === navigation) close();
      await refreshRuns(navigationRef.current === navigation ? next.run_id : null);
    } catch (err) { if (scopeRef.current === taskId && submitRequest.current === request) setError(err); }
    finally { if (submitRequest.current === request) { submitRequest.current = null; setSubmitting(false); } }
  };
  const updateFilter = (key, value) => setFilters(old => ({ ...old, [key]: value, offset: 0 }));
  const togglePerson = id => setSelected(old => old.includes(id) ? old.filter(v => v !== id) : [...old, id].slice(0, 20));
  const invalidContext = context.length > 8000;
  const coverage = data?.coverage;
  const stale = data?.freshness?.materials_changed || data?.freshness?.task_case_changed || data?.freshness?.graph_state === 'changed';
  const hasData = data && data.run.run_id === runId && data.run.task_id === taskId;
  const resultsCurrent = hasData && dataIdentity.current === queryIdentity;

  if (!taskId) return <p>请先选择任务。</p>;
  return <section className="space-y-4 text-slate-700 [overflow-wrap:anywhere] dark:text-slate-200" aria-label={view === 'people' ? '人员关系图' : '关系优先级网络'} data-testid="people-panel">
    <header><h2 className="text-lg font-semibold">{view === 'people' ? '人员关系图' : '按案情筛选关系网'}</h2>
      <p className="mt-1 text-xs leading-6 text-slate-500">人员发现读取登记材料，不按案情关联度或入报状态筛除。等级用于核查顺序；核心人物是机器建议，不代表犯罪身份。没有连线的人物仍保留。</p></header>
    <details className="rounded-xl border border-slate-200 p-3 dark:border-slate-600" open={!runs.length || !!active}>
      <summary className="cursor-pointer text-sm font-medium">人员发现与案情优先级评估</summary>
      <div className="mt-3 space-y-3">
        <label className="block text-xs">本轮案情描述（可留空，仅保留人员发现）
          <textarea aria-label="图谱评估案情" value={context} onChange={e => { edited.current = true; setContext(e.target.value); }}
            className={`${field} mt-1 min-h-24 w-full`} disabled={submitting} /></label>
        {invalidContext && <p role="alert" className="text-amber-700">案情超过8000字，请明确缩减；不会自动截断。</p>}
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label>分析人<input aria-label="图谱分析人" value={actor} maxLength={256} onChange={e => setActor(e.target.value)} className={`${field} mt-1 block`} /></label>
          <label>本轮文件上限<select aria-label="人员发现文件上限" className={`${field} mt-1 block`} value={fileLimit} onChange={e => setFileLimit(Number(e.target.value))}>{[100, 200, 500].map(v => <option key={v}>{v}</option>)}</select></label>
          <label>原图关系上限<select className={`${field} mt-1 block`} aria-label="原图关系上限" value={graphLimit} onChange={e => setGraphLimit(Number(e.target.value))}>{[500, 1000, 2000].map(v => <option key={v}>{v}</option>)}</select></label>
          <label>本轮评估目标上限<select className={`${field} mt-1 block`} aria-label="评估目标上限" value={assessmentLimit} onChange={e => setAssessmentLimit(Number(e.target.value))}>{[100, 200, 500, 1000].map(v => <option key={v}>{v}</option>)}</select></label>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={button} data-testid="discover-people" disabled={submitting || !!active || !actor.trim() || invalidContext} onClick={() => launch('discover')}>发现／更新人员与关系</button>
          <button type="button" className={button} data-testid="assess-people" disabled={submitting || !!active || selectedRun?.status !== 'completed' || !actor.trim() || !context.trim() || invalidContext} onClick={() => launch('assess')}>按当前案情评估／继续未评估</button>
        </div>
        <p className="text-xs text-slate-500">重新评估复用选定版本的冻结材料；文件变化需“发现／更新”。每轮结果分别保存，身份调整只沿用来源提及未变的人工分组。</p>
      </div>
    </details>
    {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-950/30 dark:text-rose-200">{message(error)}</p>}
    {active && <div className="rounded-xl bg-blue-50 p-3 text-sm dark:bg-blue-950/30" role="status">
      {phases[active.phase] || active.phase} · {active.progress || 0}%
      <button type="button" className={`${button} ml-3`} onClick={async () => {
        try { await service.cancelPeopleRun(taskId, active.run_id); if (scopeRef.current === taskId) await refreshRuns(); }
        catch (err) { if (scopeRef.current === taskId) setError(err); }
      }}>取消本轮</button>
    </div>}
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <label>分析版本 <select aria-label="人员图谱版本" className={field} value={runId} onChange={e => { navigationRef.current++; setRunId(e.target.value); setFilters(defaults); }}>
        {!runs.length && <option value="">尚无版本</option>}
        {runs.map(r => <option key={r.run_id} value={r.run_id}>{r.created_at} · {statusLabel[r.status] || r.status} · {r.run_id.slice(-8)}</option>)}
      </select></label>
      <button type="button" className={button} onClick={() => refreshRuns().then(() => setRefreshToken(v => v + 1)).catch(setError)}>刷新版本</button>
    </div>
    {selectedRun && !['completed', 'running'].includes(selectedRun.status) && <p role="alert">{statusLabel[selectedRun.status]}：{selectedRun.error || '可重新发起，原有版本保留。'}</p>}
    {loading && <p role="status">正在读取已保存的图谱分析…</p>}
    {hasData && <>
      <div className="rounded-xl border border-slate-200 p-3 text-xs leading-6 dark:border-slate-600" data-testid="people-coverage">
        登记文件 {coverage.registered_files} · 本轮完整处理 {coverage.complete_files} · 部分处理 {coverage.partial_files} · 不可读 {coverage.unavailable_files} · 未纳入本轮 {coverage.unprocessed_files}<br />
        识别提及 {coverage.identified_mentions} · 人员候选 {coverage.people} · 身份待区分 {coverage.ambiguous_people} · 人员关系 {coverage.person_relations}<br />
        {data.assessment_coverage.reason || `本轮评估 ${data.assessment_coverage.attempted} 项；未评估／依据不足 ${data.assessment_coverage.pending} 项。`}
        <p>完整处理指本轮文本分块已处理，不保证模型无漏识别；无法读取、截断和未处理内容不能视为没有人物。</p>
        {(coverage.partial_files > 0 || coverage.unprocessed_files > 0 || data.assessment_coverage.truncated) &&
          <p className="font-semibold text-amber-800 dark:text-amber-300">当前分析有部分覆盖或预算截断，请结合文件覆盖清单阅读。</p>}
        {data.graph_coverage.available
          ? <p>原图关系：本轮覆盖 {data.graph_coverage.captured_relations}/{data.graph_coverage.total_relations}；未读取或缺失来源 {data.graph_coverage.unread_or_missing_episodes}，来源文字截断 {data.graph_coverage.episode_text_truncated}。</p>
          : <p className="text-amber-800 dark:text-amber-300">{data.graph_coverage.warning}</p>}
        {!!coverage.identity_groups_not_carried && <p className="text-amber-800 dark:text-amber-300">{coverage.identity_groups_not_carried} 个人工分组的来源提及已变化，未自动套用，请重新核查。</p>}
      </div>
      {(stale || data.freshness.graph_state === 'unavailable') && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
        {stale ? '案情、材料或原图已变化，当前显示历史冻结结果，请更新发现或重新评估。' : '当前无法核对原图版本；下方仅代表已保存的分析结果。'}
      </p>}
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs">{view === 'people' ? '人物优先级' : '关系优先级'} <select aria-label="图谱优先级" className={field} value={filters.priority} onChange={e => updateFilter('priority', e.target.value)}>
          <option value="all">全部</option>{view === 'people' && <option value="core">核心人物候选</option>}<option value="P1">仅P1</option><option value="P1_P2">P1＋P2</option><option value="P2">仅P2</option><option value="P3">一般参考</option><option value="unassessed">未评估／依据不足</option>
        </select></label>
        <label className="text-xs">待核问题 <select aria-label="图谱待核问题" className={`${field} max-w-full`} value={filters.question_id} onChange={e => updateFilter('question_id', e.target.value)}><option value="">全部问题</option>{data.questions.map(q => <option key={q.question_id} value={q.question_id}>{q.text.slice(0, 60)}</option>)}</select></label>
        <label className="text-xs">名称搜索 <input aria-label="图谱名称搜索" className={`${field} max-w-full`} value={filters.query} maxLength={120} onChange={e => updateFilter('query', e.target.value)} /></label>
        <label className="text-xs">业务关系 <select aria-label="图谱业务关系" className={field} value={filters.relation_label} onChange={e => updateFilter('relation_label', e.target.value)}><option value="">全部关系名称</option>{(data.relation_labels || []).map(label => <option key={label}>{label}</option>)}</select></label>
        {view === 'people' && <>
          <label className="text-xs">人员范围 <select aria-label="人员范围" className={field} value={filters.identity_status} onChange={e => updateFilter('identity_status', e.target.value)}><option value="all">全部人物</option><option value="ambiguous">身份待区分</option><option value="isolated">无直接关系人物</option></select></label>
          <label className="text-xs">关系类型 <select aria-label="人员关系类型" className={field} value={filters.relation_kind} onChange={e => updateFilter('relation_kind', e.target.value)}><option value="">明确关系与待核关系</option><option value="direct">材料明确表述</option><option value="hypothesis">待核关系</option><option value="co_mentioned">共同出现（背景）</option><option value="identity_candidate">身份对应建议</option></select></label>
          <label className="text-xs">来源文件 <select aria-label="人员来源文件" className={`${field} max-w-64`} value={filters.material_id} onChange={e => updateFilter('material_id', e.target.value)}><option value="">全部来源</option>{data.materials.map(m => <option key={m.id} value={m.id}>{m.path}</option>)}</select></label>
          <label className="text-xs"><input type="checkbox" checked={filters.include_context} onChange={e => updateFilter('include_context', e.target.checked)} /> 显示一层上下文（不提升等级）</label>
        </>}
        <label className="text-xs">画布上限 <select aria-label="人员画布上限" className={field} value={filters.max_nodes} onChange={e => updateFilter('max_nodes', Number(e.target.value))}>{[100, 200, 500, 1000].map(n => <option key={n}>{n}</option>)}</select></label>
        {filters.focus_id && <button type="button" className={button} onClick={() => updateFilter('focus_id', '')}>清除查看中心</button>}
      </div>
      <div className="flex flex-wrap gap-3 text-xs">{Object.entries(PEOPLE_LEVELS).filter(([key]) => view === 'people' || key !== 'core').map(([key, style]) =>
        <span key={key} style={{ color: style.color }}>● {style.label}</span>)}<span>淡色为上下文；白圈仅表示当前选择</span></div>
      {!resultsCurrent ? <p role="status">{loading ? '正在更新筛选结果…' : '筛选结果尚未就绪，可点击刷新版本重试。'}</p> : <>
      <p className="text-xs">筛选命中 {data.total_items} 项；画布显示 {data.nodes.length} 个节点、{data.links.length} 条关系。{data.display_truncated && <strong className="text-amber-800 dark:text-amber-300">画布已截断，清单仍可分页查看。</strong>}</p>
      {data.nodes.length ? <Canvas nodes={data.nodes} links={data.links} selectedId={detailId}
        onNode={node => view === 'people' ? openDetail(node.id) : updateFilter('focus_id', node.id)} onLink={link => openDetail(link.id)} />
        : <p className="rounded-xl border border-dashed p-5 text-sm">当前条件没有可显示的节点；不代表材料中没有相关人物或关系。</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" data-testid="people-list"><thead><tr>{view === 'people' && <th className="p-2">选择</th>}<th className="p-2">{view === 'people' ? '人物／别名' : '关系'}</th><th className="p-2">核查等级</th><th className="p-2">状态与来源</th><th className="p-2">操作</th></tr></thead>
          <tbody>{data.items.map(item => <tr key={item.id} className="border-t border-slate-100 dark:border-slate-700">
            {view === 'people' && <td className="p-2"><input type="checkbox" aria-label={`选择人员 ${item.name}`} checked={selected.includes(item.id)} onChange={() => togglePerson(item.id)} /></td>}
            <td className="p-2">{item.name || `${item.source_name} — ${item.label} → ${item.target_name}`}{item.names?.length > 1 && <p className="text-xs text-slate-500">{item.names.join('、')}</p>}</td>
            <td className="p-2"><Badge assessment={item.assessment} /></td>
            <td className="p-2 text-xs">{IDENTITY_LABELS[item.identity_status] || '机器提取，待核验'}{item.mention_count != null && ` · ${item.mention_count} 条提及 · ${item.relation_count} 条关系`}</td>
            <td className="p-2"><button type="button" className="text-blue-700 underline dark:text-blue-300" onClick={() => openDetail(item.id)}>依据与来源</button>{view === 'people' && <button type="button" className="ml-2 text-xs text-blue-700 dark:text-blue-300" onClick={() => updateFilter('focus_id', item.id)}>设为查看中心</button>}</td>
          </tr>)}</tbody></table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" className={button} disabled={!filters.offset} onClick={() => setFilters(f => ({ ...f, offset: Math.max(0, f.offset - f.limit) }))}>上一页清单</button>
        <span>{data.total_items ? filters.offset + 1 : 0}—{Math.min(filters.offset + filters.limit, data.total_items)} / {data.total_items}</span>
        <button type="button" className={button} disabled={filters.offset + filters.limit >= data.total_items} onClick={() => setFilters(f => ({ ...f, offset: f.offset + f.limit }))}>下一页清单</button>
      </div>
      {view === 'people' && <details className="rounded-xl border p-3 dark:border-slate-600">
        <summary className="cursor-pointer text-sm">身份归组调整 · 已选 {selected.length} 个人员候选</summary>
        <p className="mt-2 text-xs">同名不自动合并。人工调整生成新版本并保留来源；有冲突身份号码时不能直接合并。</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input aria-label="合并后显示名称" className={field} placeholder="合并后显示名称（可选）" value={displayName} maxLength={80} onChange={e => setDisplayName(e.target.value)} />
          <input aria-label="身份调整依据" className={`${field} min-w-0 flex-1`} placeholder="填写调整依据" value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} />
          <button type="button" className={button} disabled={submitting || !!active || selected.length < 2 || !reason.trim() || !actor.trim() || data.freshness.materials_changed} onClick={() => revise('merge')}>将所选候选归组为一人</button>
        </div>
      </details>}
      </>}
      <details className="rounded-xl border p-3 text-xs leading-6 dark:border-slate-600">
        <summary className="cursor-pointer font-medium">文件覆盖与版本依据</summary>
        <p className="mt-2">规则 {data.policy_version} · 模型 {data.models.join('、') || '无模型成功记录'} · 机器建议，待人工核验</p>
        <p className="break-all">版本 {runId} · 输入哈希 {data.run.input_hash} · 结果哈希 {data.run.result_hash}</p>
        <details className="mt-2"><summary className="cursor-pointer">本轮冻结案情</summary><p className="whitespace-pre-wrap">{data.run.case_description || '未提供案情'}</p></details>
        <p>分块调用 {data.discovery_coverage.chunks_attempted} 次，失败 {data.discovery_coverage.chunks_failed} 次；人物出现次数仅指本轮识别提及，不能推定材料已穷尽识别。</p>
        <ul className="mt-2 max-h-64 space-y-2 overflow-auto">{data.materials.map(m => <li key={m.id} className="rounded border p-2 dark:border-slate-700">
          <p>{m.path} · {m.status === 'complete' ? '本轮处理完成' : m.status === 'partial' ? '部分处理' : '不可读'}</p>
          <p>已处理文本 {m.processed_characters}/{m.original_characters} 字符 · {peopleBasisLabel(m.kind)}</p>
          {!!m.limitations.length && <p className="text-amber-800 dark:text-amber-300">限制：{m.limitations.map(peopleLimitLabel).join('；')}</p>}
        </li>)}</ul>
        {data.identity_history.length > 0 && <details className="mt-2"><summary>人工身份调整记录</summary>{data.identity_history.map((h, i) => <p key={h.revision || i}>{h.actor} · {h.operation} · {h.reason}</p>)}</details>}
      </details>
    </>}
    {dialogOpen && createPortal(<div className="fixed inset-0 z-[80] !m-0 flex justify-end text-slate-700 dark:text-slate-200" data-testid="people-source-overlay">
      <button type="button" tabIndex={-1} className="absolute inset-0 bg-slate-950/40" aria-label="关闭人物来源遮罩" onClick={close} />
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="人物与关系来源" tabIndex={-1} className="relative h-full w-full max-w-2xl overflow-y-auto bg-white p-5 outline-none [overflow-wrap:anywhere] dark:bg-slate-900">
        <header className="flex justify-between gap-2"><h3 className="font-semibold">依据与来源</h3><button type="button" aria-label="关闭人物来源" onClick={close}>×</button></header>
        {detailError && <p role="alert">{message(detailError)}</p>}
        {!detail && !detailError && <p role="status">正在读取冻结来源…</p>}
        {detail && <div className="mt-4 space-y-4">
          <h4 className="font-semibold">{detail.target.name || detail.target.label}</h4>
          <Badge assessment={detail.assessment} /><p className="text-sm leading-7">{detail.assessment.reason}</p>
          <p className="text-xs">机器建议与身份归组状态分别保留；查看中心不会改变核心人物标记。</p>
          {detail.assessment.refs.map((ref, i) => <blockquote key={i} className="border-l-2 border-blue-300 pl-3 text-sm">{ref.quote}<p className="text-xs text-slate-500">依据类型：{peopleBasisLabel(ref.basis_type)} · 来源 {ref.source_id}</p></blockquote>)}
          {detail.mentions.length > 0 && <section>
            <h4 className="font-medium">人物提及与身份依据</h4>
            {detail.mentions.map(m => <div key={m.id} className="mt-2 rounded border p-3 text-sm dark:border-slate-700">
              <label className="flex items-center gap-2"><input type="checkbox" aria-label={`拆分提及 ${m.id}`} checked={selectedMentions.includes(m.id)} onChange={e => setSelectedMentions(v => e.target.checked ? [...v, m.id] : v.filter(id => id !== m.id))} />{m.name}</label>
              <p className="mt-2 whitespace-pre-wrap">{m.ref.quote}</p>
              <p className="mt-1 text-xs text-slate-500">解析文本字符位置 {m.ref.start}—{m.ref.end}，非原文件页码或磁盘偏移。{m.ref.ambiguous && '引文在该片段中有多处匹配。'}</p>
              {m.identity_quote && <p className="mt-1 text-xs">身份对应原文：{m.identity_quote}</p>}
            </div>)}
            {detail.mentions.length > 1 && <div className="mt-3 space-y-2">
              <textarea aria-label="拆分依据" className={`${field} w-full`} value={reason} maxLength={1000} onChange={e => setReason(e.target.value)} placeholder="选中需要另行归组的部分提及，说明拆分依据" />
              <button type="button" className={button} disabled={submitting || !!active || !actor.trim() || !reason.trim() || !selectedMentions.length || selectedMentions.length === detail.mentions.length || detail.freshness.materials_changed} onClick={() => revise('split')}>将所选提及拆为另一人员候选</button>
            </div>}
          </section>}
          {detail.refs.map((ref, i) => <p key={`${ref.source_id}-${i}`} className="text-xs">{ref.basis_type === 'case_description' ? '仅案情来源（不能自证）' : '冻结来源片段'}：{ref.quote}</p>)}
          {detail.sources.map(source => <section key={source.id} className="rounded-xl border p-3 dark:border-slate-700">
            <h4 className="break-all text-sm font-medium">{source.path || source.source_description || source.id}</h4>
            <p className="mt-1 text-xs">{peopleBasisLabel(source.kind)} · 本轮冻结内容{source.preview_truncated ? ' · 预览仅前12000字符' : ''}</p>
            {source.source_hash && <p className="mt-1 break-all text-[10px]">来源 SHA-256 {source.source_hash}</p>}
            <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-3 text-xs leading-6 dark:bg-slate-800">{source.text || '没有可读内容'}</pre>
            {source.evidence_key && <Link className="mt-2 inline-block text-xs text-blue-700 dark:text-blue-300" to={`/graph-source-file?task_id=${encodeURIComponent(taskId)}&evidence_key=${encodeURIComponent(source.evidence_key)}`}>打开当前任务文件副本（可能与冻结版本不同）</Link>}
          </section>)}
          {!detail.sources.length && <p>本轮没有可核对的来源，不回退使用其他任务或同名文件。</p>}
          {detail.relations.length > 0 && <section><h4 className="font-medium">关联记录（不自动提升等级）</h4>{detail.relations.map(r => <button type="button" key={r.id} className={`${button} m-1`} onClick={() => openDetail(r.id)}>{r.label} · {r.kind}</button>)}</section>}
        </div>}
      </div>
    </div>, document.body)}
  </section>;
}
