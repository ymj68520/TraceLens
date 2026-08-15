import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Microscope, RefreshCw } from 'lucide-react';
import Button from '../../components/common/Button';
import Spinner from '../../components/common/Spinner';
import useInvestigationEvents from './hooks/useInvestigationEvents';
import useEventEvidence from './hooks/useEventEvidence';
import InvestigationTimeline from './components/InvestigationTimeline';
import EventEvidencePanel from './components/EventEvidencePanel';
import AnalysisWorkspace from './components/AnalysisWorkspace';

export default function Investigation() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  const requestedEvent = searchParams.get('event');
  const [selectedEventId, setSelectedEventId] = useState(requestedEvent);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState(null);
  const [claimEvidenceScope, setClaimEvidenceScope] = useState(null);
  const { overview, events, loading, error, refresh: refreshEvents } = useInvestigationEvents(taskId);
  const { evidence, loading: evidenceLoading, error: evidenceError, refresh: refreshEvidence } = useEventEvidence(taskId, selectedEventId);
  const selectedEvent = useMemo(() => events.find((event) => event.id === selectedEventId) || null, [events, selectedEventId]);

  useEffect(() => {
    if (!selectedEventId && events.length) setSelectedEventId(events[0].id);
    if (selectedEventId && events.length && !events.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(events[0].id);
      setSelectedEvidenceKey(null);
      setClaimEvidenceScope(null);
    }
  }, [events, selectedEventId]);

  const selectEvent = (eventId) => {
    setSelectedEventId(eventId);
    setSelectedEvidenceKey(null);
    setClaimEvidenceScope(null);
  };

  const traceClaim = (claim) => {
    const keys = (claim.evidence_refs || []).map((ref) => ref.evidence_key);
    setClaimEvidenceScope({ claim, keys });
    setSelectedEvidenceKey(null);
  };

  const traceEvidence = (evidenceKey) => {
    setClaimEvidenceScope((scope) => scope ? { ...scope, keys: [evidenceKey] } : scope);
    setSelectedEvidenceKey(evidenceKey);
  };

  const clearClaimScope = () => {
    setClaimEvidenceScope(null);
    setSelectedEvidenceKey(null);
  };

  if (!taskId) {
    return <div className="h-[calc(100vh-7rem)] flex items-center justify-center"><div className="max-w-lg text-center"><Microscope className="mx-auto h-14 w-14 text-primary-500" /><h1 className="mt-4 text-2xl font-bold text-slate-900 dark:text-white">二次调查分析工作台</h1><p className="mt-2 text-slate-500">请先从顶部任务选择器选择一个已完成初次自动分析的任务。</p></div></div>;
  }

  if (loading && !overview) return <div className="h-[calc(100vh-7rem)] flex items-center justify-center"><Spinner size="xl" /></div>;
  if (error) return <div className="m-6 rounded-xl border border-rose-300 bg-rose-50 dark:bg-rose-950/20 p-5 text-rose-700"><AlertTriangle className="inline mr-2" />调查工作台加载失败：{error.message}<Button size="sm" variant="secondary" className="ml-4" onClick={refreshEvents}>重试</Button></div>;

  return (
    <div className="h-[calc(100vh-6.5rem)] flex flex-col gap-3">
      <header className="flex items-center justify-between rounded-2xl glass px-5 py-3">
        <div><h1 className="text-xl font-bold text-slate-900 dark:text-white">Investigation / 二次调查分析</h1><p className="text-xs text-slate-500">初次证据只读 · 分析员上下文 · 版本化二次分析 · 可追溯到真实 Evidence</p></div>
        <div className="flex items-center gap-4 text-xs text-slate-500"><span>{overview?.event_count || 0} Events</span><span>{overview?.analysis_count || 0} Analyses</span><span>{overview?.report_evidence_count || 0} Report Evidence</span><Link to={`/investigation/report?task_id=${encodeURIComponent(taskId)}`} className="font-semibold text-primary-600 hover:text-primary-500 dark:text-primary-300">Final Report Viewer</Link><Button size="sm" variant="ghost" icon={RefreshCw} onClick={refreshEvents}>刷新</Button></div>
      </header>
      <main className="grid min-h-0 flex-1 grid-cols-[minmax(250px,0.8fr)_minmax(300px,0.9fr)_minmax(440px,1.45fr)] gap-3">
        <section className="min-h-0 overflow-hidden rounded-2xl glass"><EventEvidencePanel taskId={taskId} eventId={selectedEventId} event={selectedEvent} evidence={evidence} loading={evidenceLoading} error={evidenceError} selectedEvidenceKey={selectedEvidenceKey} claimEvidenceScope={claimEvidenceScope} onClearClaimScope={clearClaimScope} onSelect={(key) => { setClaimEvidenceScope(null); setSelectedEvidenceKey(key); }} onRefresh={refreshEvidence} /></section>
        <section className="min-h-0 overflow-hidden rounded-2xl glass"><div className="border-b border-slate-200/60 dark:border-slate-700/50 px-4 py-3 text-sm font-semibold">Investigation Timeline</div><InvestigationTimeline events={events} selectedEventId={selectedEventId} onSelect={selectEvent} loading={loading} /></section>
        <section className="min-h-0 overflow-hidden rounded-2xl glass"><AnalysisWorkspace taskId={taskId} event={selectedEvent} eventId={selectedEventId} evidenceKey={selectedEvidenceKey} onRefreshEvents={refreshEvents} onTraceClaim={traceClaim} onTraceEvidence={traceEvidence} onEvidenceChanged={async () => { await Promise.all([refreshEvents(), refreshEvidence()]); }} /></section>
      </main>
    </div>
  );
}
