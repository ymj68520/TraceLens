import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import * as defaultService from '../../services/eventGraphService';
import { listPeopleRuns } from '../../services/peopleGraphService';
import EventGraphCanvas from './EventGraphCanvas';
import { edgeLabel, edgeNames, eventKinds } from './eventGraphConstants';
import EventGraphDetail from './EventGraphDetail';

const field = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-900';
const button = 'rounded-lg border border-slate-300 px-3 py-2 text-sm disabled:opacity-50 dark:border-slate-600';
const defaults = { query: '', focus_id: '', relation_kind: '', max_nodes: 200, offset: 0, limit: 25 };
const errorText = error => error?.data?.detail || error?.response?.data?.detail || error?.message || '请求未完成，请重试';
const statusNames = { running: '分析中', completed: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' };
const viewNames = { events: '事件—证据图', evidence: '证据关联图', associations: '人员—事件与事件智能关联' };

export default function EventGraphPanel({ taskId, view, initialRunId = '', onRunChange, service = defaultService, peopleLoader = listPeopleRuns, pollMs = 2000 }) {
  const [runId, setRunId] = useState(initialRunId), [runs, setRuns] = useState([]), [peopleRuns, setPeopleRuns] = useState([]);
  const [data, setData] = useState(null), [catalog, setCatalog] = useState([]), [filters, setFilters] = useState(defaults);
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [refresh, setRefresh] = useState(0);
  const [actor, setActor] = useState(''), [context, setContext] = useState(''), [peopleId, setPeopleId] = useState('');
  const [eventIds, setEventIds] = useState([]), [maxPairs, setMaxPairs] = useState(100), [submitting, setSubmitting] = useState(false);
  const [detailId, setDetailId] = useState(''), [detail, setDetail] = useState(null), [detailError, setDetailError] = useState('');
  const mounted = useRef(false), navigation = useRef(0), queryRef = useRef(''), detailSeq = useRef(0), submitRef = useRef(false);
  const mutations = useRef(0);
  const chosen = runs.find(r => r.run_id === runId), active = runs.find(r => r.status === 'running');
  const filterKey = JSON.stringify({ ...filters, view });
  const queryKey = `${taskId}|${runId}|${filterKey}|${refresh}`;
  queryRef.current = queryKey;

  useEffect(() => {
    mounted.current = true;
    let alive = true;
    const nav = navigation, details = detailSeq, version = mutations.current;
    service.listEventRuns(taskId).then(r => { if (alive && version === mutations.current) setRuns(r.runs); }).catch(e => { if (alive) setError(errorText(e)); });
    peopleLoader(taskId).then(r => { if (alive) setPeopleRuns(r.runs.filter(row => row.status === 'completed')); }).catch(e => { if (alive) setError(`人员版本读取失败：${errorText(e)}`); });
    service.getEventView(taskId, { view: 'events', max_nodes: 1, limit: 1 }).then(r => { if (alive) setCatalog(r.available_events || []); }).catch(e => { if (alive) setError(errorText(e)); });
    return () => { alive = false; mounted.current = false; details.current++; nav.current++; };
  }, [service, peopleLoader, taskId, refresh]);

  useEffect(() => { onRunChange?.(runId); }, [runId, onRunChange]);
  useEffect(() => {
    let alive = true, timer;
    if (!active) return undefined;
    const poll = async () => {
      try {
        const row = await service.getEventRun(taskId, active.run_id);
        if (!alive) return;
        setRuns(old => old.map(r => r.run_id === row.run_id && !(r.status !== 'running' && row.status === 'running') ? row : r));
        if (row.status !== 'running') return;
      } catch (e) { if (alive) setError(errorText(e)); }
      if (alive) timer = setTimeout(poll, pollMs);
    };
    poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [active?.run_id, service, taskId, pollMs]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true;
    setDetailId(''); setDetail(null); setData(null); setLoading(false);
    if (runId && chosen?.status !== 'completed') return undefined;
    if (view === 'associations' && !runId) return undefined;
    setLoading(true);
    const request = runId ? service.getEventRunGraph(taskId, runId, JSON.parse(filterKey)) : service.getEventView(taskId, JSON.parse(filterKey));
    request.then(result => { if (alive && queryRef.current === queryKey) { setData(result); setError(''); } })
      .catch(e => { if (alive && queryRef.current === queryKey) setError(errorText(e)); })
      .finally(() => { if (alive && queryRef.current === queryKey) setLoading(false); });
    return () => { alive = false; };
  }, [taskId, runId, chosen?.status, view, filterKey, queryKey, service]);

  const changeFilter = (key, value) => setFilters(old => ({ ...old, [key]: value, offset: 0 }));
  const selectRun = id => { navigation.current++; detailSeq.current++; setRunId(id); setFilters(defaults); };
  const openDetail = async id => {
    const sequence = ++detailSeq.current, identity = queryKey;
    setDetailId(id); setDetail(null); setDetailError('');
    try {
      const result = runId ? await service.getEventRunDetail(taskId, runId, id) : await service.getEventDetail(taskId, id, data.source_version);
      if (mounted.current && sequence === detailSeq.current && queryRef.current === identity) setDetail(result);
    } catch (e) { if (mounted.current && sequence === detailSeq.current && queryRef.current === identity) setDetailError(errorText(e)); }
  };
  const launch = async () => {
    if (submitRef.current || active || !actor.trim()) return;
    submitRef.current = true; setSubmitting(true); setError('');
    const nav = navigation.current;
    try {
      const row = await service.startEventRun({ task_id: taskId, requested_by: actor.trim(), case_description: context,
        people_run_id: peopleId || null, event_ids: eventIds, max_pairs: maxPairs });
      if (!mounted.current) return;
      mutations.current++;
      setRuns(old => [row, ...old.filter(r => r.run_id !== row.run_id)]);
      if (navigation.current === nav) selectRun(row.run_id);
    } catch (e) { if (mounted.current) setError(errorText(e)); }
    finally { submitRef.current = false; if (mounted.current) setSubmitting(false); }
  };
  const cancel = async () => {
    try {
      const row = await service.cancelEventRun(taskId, active.run_id);
      if (mounted.current) { mutations.current++; setRuns(old => old.map(r => r.run_id === row.run_id ? row : r)); }
    } catch (e) { if (mounted.current) setError(errorText(e)); }
  };
  const coverage = data?.coverage, analysis = data?.analysis_coverage;
  const stale = data?.freshness && (data.freshness.investigation !== 'unchanged' || ['changed', 'unavailable'].includes(data.freshness.people_materials) || data.freshness.newer_people_version || data.freshness.task_case_changed);

  return <section className="min-w-0 space-y-4 text-slate-700 [overflow-wrap:anywhere] dark:text-slate-200" aria-label={viewNames[view]} data-testid="event-graph-panel">
    <header><h2 className="text-lg font-semibold">{viewNames[view]}</h2><p className="mt-1 text-sm text-slate-500">已有事件按登记版本展示。共同材料不代表事件相同，人员提及不代表参与；无连线的事件仍保留。</p></header>
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-0 flex-1 text-xs">数据版本<select aria-label="事件图谱版本" className={field} value={runId} onChange={e => selectRun(e.target.value)}><option value="">当前已登记数据（只读）</option>{runs.map(r => <option key={r.run_id} value={r.run_id}>{r.created_at} · {statusNames[r.status] || r.status} · {r.run_id.slice(-8)}</option>)}</select></label>
      <button className={button} onClick={() => setRefresh(v => v + 1)}>刷新图谱数据</button>
      <Link className={`${button} text-blue-600`} to={`/investigation?task_id=${encodeURIComponent(taskId)}`}>调查工作台</Link>
    </div>
    <details className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
      <summary className="cursor-pointer font-medium">发起人员—事件与事件关联分析</summary>
      <p className="my-3 text-sm">仅分析选择的已有事件和冻结材料。需要人物参与线索时选择已完成的人员版本；不重新运行人员发现。分析生成新版本，结果均为待核建议。</p>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs">分析人<input aria-label="事件分析人" className={field} value={actor} maxLength={256} onChange={e => setActor(e.target.value)} /></label>
        <label className="text-xs">人员版本<select aria-label="关联人员版本" className={field} value={peopleId} onChange={e => setPeopleId(e.target.value)}><option value="">仅分析事件之间的关联</option>{peopleRuns.map(r => <option value={r.run_id} key={r.run_id}>{r.created_at} · {r.run_id.slice(-8)}</option>)}</select></label>
        <label className="text-xs">事件范围（可多选，最多50个；不选择时按标识顺序取前50个）<select multiple aria-label="关联事件范围" className={`${field} h-28`} value={eventIds} onChange={e => setEventIds([...e.target.selectedOptions].map(o => o.value).slice(0, 50))}>{catalog.map(e => <option value={e.event_id} key={e.event_id}>{e.title} · v{e.version}</option>)}</select></label>
        <label className="text-xs">案情语境（可选，不作为材料依据）<textarea aria-label="事件分析案情" className={`${field} h-28`} value={context} maxLength={8000} onChange={e => setContext(e.target.value)} /></label>
        <label className="text-xs">本轮最多评估的目标对<select aria-label="事件关联评估上限" className={field} value={maxPairs} onChange={e => setMaxPairs(Number(e.target.value))}>{[25, 100, 250, 500].map(n => <option key={n}>{n}</option>)}</select></label>
      </div>
      <button className={`${button} mt-3 bg-blue-600 text-white`} disabled={submitting || !!active || !actor.trim() || !catalog.length} onClick={launch}>{submitting ? '正在提交…' : '生成智能关联新版本'}</button>
      {!peopleRuns.length && <p className="mt-2 text-xs">暂无已完成的人员版本；可先在“人员关系图”中发现人员，或仅分析事件。</p>}
    </details>
    {active && <div className="flex flex-wrap items-center gap-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">正在分析 {active.progress || 0}%<button className={button} onClick={cancel}>取消事件关联分析</button></div>}
    {chosen && ['failed', 'cancelled', 'interrupted'].includes(chosen.status) && <p role="status">{statusNames[chosen.status]}：{chosen.error}。可以选择已有完成版本或重新发起。</p>}
    {error && <p role="alert" className="text-orange-700">{error}</p>}
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="text-xs">查找事件、人物或材料<input aria-label="事件图谱搜索" className={field} value={filters.query} onChange={e => changeFilter('query', e.target.value)} /></label>
      <label className="text-xs">关系类别<select aria-label="事件图谱关系类别" className={field} value={filters.relation_kind} onChange={e => changeFilter('relation_kind', e.target.value)}><option value="">全部（保留孤立节点）</option>{Object.entries(edgeNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="text-xs">画布节点上限<select aria-label="事件图谱节点上限" className={field} value={filters.max_nodes} onChange={e => changeFilter('max_nodes', Number(e.target.value))}>{[100, 200, 500, 1000].map(n => <option key={n}>{n}</option>)}</select></label>
    </div>
    {loading && <p role="status">正在读取图谱…</p>}
    {view === 'associations' && !runId && <p>请选择已完成的智能关联版本，或展开上方入口显式发起分析。</p>}
    {stale && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">当前来源或人员版本已有变化，或暂无法核对。这里继续展示本轮冻结结果；请查看来源版本，必要时生成新版本。</p>}
    {data && <>
      <div className="rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800">
        <p>已读取事件 {coverage.events_captured} / {coverage.events_total} · 关联材料 {coverage.evidence_captured} / {coverage.evidence_total} · 匹配节点 {data.matched_nodes} · 关系 {data.matched_links}</p>
        {(coverage.truncated || data.display_truncated) && <p className="font-medium text-orange-700">数据范围或画布有截断；清单独立分页。未显示不等于不存在。</p>}
        {!!(coverage.source_text_truncated || coverage.source_payload_truncated) && <p>来源文本截断 {coverage.source_text_truncated} 份 · 快照展示截断 {coverage.source_payload_truncated} 份</p>}
        <p className="mt-1 text-xs">{coverage.time_policy || '行为发生时间未知时不自动排序；没有记录不能解释成没有活动。'}</p>
        {analysis && <p className="mt-2">分析事件 {analysis.selected_events}（未选 {analysis.events_not_selected}） · 候选目标对 {analysis.candidate_pairs} · 已尝试 {analysis.attempted_pairs} · 未纳入 {analysis.omitted_pairs} · 依据不足 {analysis.insufficient_source_pairs} · 调用失败 {analysis.failed_pairs} · 无效建议 {analysis.invalid_suggestions} · 来源片段受限 {analysis.source_limited_pairs} · 材料版本未核对 {analysis.unverified_bindings}</p>}
        {analysis && <p className="mt-1 text-xs">没有生成建议不等于没有关联；请结合覆盖范围和失败数量核查。</p>}
        {analysis && <p className="mt-1 text-xs">人员读取 {analysis.people_captured ?? 0} / {analysis.people_total ?? 0} · 已绑定提及 {analysis.mentions_captured ?? 0} / {analysis.mentions_total ?? 0}（每人最多 {analysis.mention_limit_per_person ?? 20} 条，未绑定可能因范围或预算限制） · 未展示提及边 {analysis.mention_links_omitted ?? 0}</p>}
        <details className="mt-2 text-xs"><summary>筛选条件与版本依据</summary><p>来源版本：{data.source_version}</p><p>统计／规则版本：{data.policy_version}</p><p>去重：{coverage.deduplication}</p>{data.people_run_id && <p>人员版本：{data.people_run_id} · 结果哈希：{data.people_result_hash}</p>}<pre className="whitespace-pre-wrap">{JSON.stringify(data.filters, null, 2)}</pre>{data.run && <p>分析语境：{data.run.case_description || '未提供'} · 模型：{data.models.join('、') || '未成功调用'}</p>}</details>
      </div>
      <p className="text-xs text-slate-500">◇ 调查事件 · □ 证据材料 · ○ 人员 · 小圆点为分析／结论；虚线表示提及或待核建议。人物等级沿用所选人员版本，事件不继承人物等级。</p>
      {!!data.nodes.length && <EventGraphCanvas nodes={data.nodes} links={data.links} onSelect={openDetail} />}
      {!data.nodes.length && <p className="p-5 text-sm">当前范围没有可展示的节点。请核对筛选条件、调查事件登记情况和来源覆盖范围。</p>}
      {detailId && <EventGraphDetail taskId={taskId} detail={detail} error={detailError} onClose={() => { detailSeq.current++; setDetailId(''); setDetail(null); }} />}
      <div className="space-y-2"><h3 className="font-medium">节点与关系清单 · {data.total_items}</h3>
        {data.items.map(item => <button className="block w-full rounded-lg border border-slate-200 p-3 text-left text-sm dark:border-slate-700" key={item.id} onClick={() => openDetail(item.id)}>{item.item_type === 'node' ? `${eventKinds[item.kind]} · ${item.name}` : `${item.source_name} → ${edgeLabel(item)} → ${item.target_name}`}{item.status === 'machine_suggestion' && <span className="ml-2 text-purple-600">机器建议 · 待核查</span>}</button>)}
        <div className="flex gap-3"><button className={button} disabled={!filters.offset} onClick={() => setFilters(old => ({ ...old, offset: Math.max(0, old.offset - old.limit) }))}>上一页</button><button className={button} disabled={filters.offset + filters.limit >= data.total_items} onClick={() => setFilters(old => ({ ...old, offset: old.offset + old.limit }))}>下一页</button></div>
      </div>
    </>}
  </section>;
}
