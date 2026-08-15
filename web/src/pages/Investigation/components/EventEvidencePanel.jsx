import { useEffect, useMemo, useState } from 'react';
import { Plus, X } from 'lucide-react';
import Button from '../../../components/common/Button';
import Spinner from '../../../components/common/Spinner';
import EvidenceCard from './EvidenceCard';
import EvidencePicker from './EvidencePicker';

const filters = [
  ['all', '全部'], ['primary', 'Primary'], ['supporting', 'Supporting'],
  ['contradicting', 'Contradicting'], ['report', 'Report'], ['unreviewed', 'Unreviewed'],
];

export default function EventEvidencePanel({ taskId, eventId, event, evidence, loading, error, selectedEvidenceKey, claimEvidenceScope, onClearClaimScope, onSelect, onRefresh }) {
  const [filter, setFilter] = useState('all');
  const [pickerOpen, setPickerOpen] = useState(false);
  const visible = useMemo(() => evidence.filter((item) => {
    if (claimEvidenceScope) return claimEvidenceScope.keys.includes(item.evidence_key);
    if (filter === 'all') return true;
    if (filter === 'report') return Boolean(item.report_usage);
    if (filter === 'unreviewed') return !item.analysis_status || item.analysis_status === 'review_pending';
    return item.role === filter;
  }), [evidence, filter, claimEvidenceScope]);
  const historicalKeys = useMemo(() => claimEvidenceScope?.keys?.filter((key) => !evidence.some((item) => item.evidence_key === key)) || [], [claimEvidenceScope, evidence]);
  const historicalKeySignature = historicalKeys.join('|');
  const [historicalResolution, setHistoricalResolution] = useState({});
  const hasCitations = Boolean(claimEvidenceScope?.keys?.length);
  useEffect(() => {
    let active = true;
    if (!historicalKeys.length) { setHistoricalResolution({}); return undefined; }
    Promise.all(historicalKeys.map(async (key) => {
      try {
        const response = await import('../../../services/investigationService').then(({ getEvidenceDetail }) => getEvidenceDetail(taskId, key));
        return [key, { resolution: 'resolved', detail: response.evidence }];
      } catch (err) { return [key, { resolution: 'unavailable', error: err }]; }
    })).then((entries) => { if (active) setHistoricalResolution(Object.fromEntries(entries)); });
    return () => { active = false; };
  }, [taskId, historicalKeys, historicalKeySignature]);

  return (
    <div className="h-full flex flex-col" data-testid="evidence-panel">
      <div className="p-3 border-b border-slate-200/60 dark:border-slate-700/50">
        <div className="flex items-center justify-between gap-2"><div className="text-sm font-semibold text-slate-900 dark:text-slate-100">关联证据 <span className="text-slate-400 font-normal">{evidence.length}</span></div><Button size="sm" variant="ghost" icon={Plus} disabled={!eventId || Boolean(claimEvidenceScope)} onClick={() => setPickerOpen(true)}>添加</Button></div>
        {claimEvidenceScope && <div className="mt-2 rounded-lg border border-violet-200 bg-violet-50 p-2 text-xs text-violet-700"><div className="flex items-start justify-between gap-2"><span>Claim Evidence Scope：{claimEvidenceScope.claim?.claim_text || 'selected claim'}</span><button type="button" onClick={onClearClaimScope} aria-label="clear claim scope"><X size={14} /></button></div><div className="mt-1">{hasCitations ? `当前 Event ${visible.length} · 历史引用 ${historicalKeys.length}` : '该 Claim 没有 Evidence 引用'}</div></div>}
        <div className="mt-2 flex flex-wrap gap-1">
          {!claimEvidenceScope && filters.map(([value, label]) => (
            <button key={value} type="button" onClick={() => setFilter(value)} className={`rounded-lg px-2 py-1 text-[11px] ${filter === value ? 'bg-primary-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {error && <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-xs text-rose-700">证据加载失败：{error.message}<button type="button" className="ml-2 underline" onClick={onRefresh}>重试</button></div>}
        {event?.source_cluster_key && !claimEvidenceScope && (
          <EvidenceCard
            evidence={{ evidence_key: event.source_cluster_key, evidence_type: 'event_cluster', title: event.seed_title || event.title, timestamp: event.start_time, initial_summary: event.seed_summary || event.summary, role: 'primary' }}
            selected={selectedEvidenceKey === event.source_cluster_key}
            onClick={() => onSelect(event.source_cluster_key)}
          />
        )}
        {loading ? <div className="h-full flex items-center justify-center"><Spinner /></div> : visible.length || historicalKeys.length ? <>
          {visible.map((item) => <EvidenceCard key={item.evidence_key} evidence={item} selected={selectedEvidenceKey === item.evidence_key} onClick={() => onSelect(item.evidence_key)} />)}
          {historicalKeys.map((key) => { const item = historicalResolution[key]; const unavailable = item?.resolution === 'unavailable'; return <div key={key} className={`rounded-xl border p-3 text-xs ${unavailable ? 'border-rose-300 bg-rose-50 text-rose-800' : 'border-amber-300 bg-amber-50 text-amber-800'}`}><div className="font-medium">{unavailable ? 'Evidence unavailable / unresolved' : 'Claim 历史引用 / 已不属于当前 Event'}</div><div className="mt-1 break-all">{key}</div>{!unavailable && item?.resolution === 'resolved' && <button type="button" className="mt-2 underline" onClick={() => onSelect(key)}>查看证据</button>}</div>; })}
        </> : <div className="py-10 text-center text-sm text-slate-500">该筛选条件下没有证据</div>}
      </div>
      <EvidencePicker taskId={taskId} eventId={eventId} open={pickerOpen} onClose={() => setPickerOpen(false)} onLinked={onRefresh} />
    </div>
  );
}
