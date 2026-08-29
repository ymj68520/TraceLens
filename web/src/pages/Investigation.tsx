import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Microscope, RefreshCw, Plus } from 'lucide-react';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import { useToast } from '../components/ui/Toast';
import {
  getOverview,
  getInvestigationEvents,
  getEventEvidence,
  createInvestigationEvent,
  captureInvestigationSnapshot,
  listInvestigationEvidence,
} from '../services/investigationService';
import { errorMessage, formatDateTime, cx } from '../lib/utils';
import EvidenceDetailPanel from '../components/investigation/EvidenceDetailPanel';

interface InvEvent {
  id: string;
  title: string;
  summary?: string;
  created_at?: string;
  status?: string;
  [key: string]: unknown;
}

interface EvidenceRow {
  evidence_key: string;
  file_path?: string;
  kind?: string;
  [key: string]: unknown;
}

export default function Investigation() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id') || searchParams.get('taskId');
  const toast = useToast();

  const [overview, setOverview] = useState<{ event_count?: number; analysis_count?: number; report_evidence_count?: number } | null>(null);
  const [events, setEvents] = useState<InvEvent[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [allEvidence, setAllEvidence] = useState<EvidenceRow[]>([]);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedEvidenceKey, setSelectedEvidenceKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEventTitle, setNewEventTitle] = useState('');
  const [creatingEvent, setCreatingEvent] = useState(false);

  const refreshEvents = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const [ov, ev, allEv] = await Promise.all([
        getOverview(taskId) as Promise<{ event_count?: number }>,
        getInvestigationEvents(taskId) as Promise<{ events?: InvEvent[] } | InvEvent[]>,
        listInvestigationEvidence(taskId) as Promise<{ evidence?: EvidenceRow[] } | EvidenceRow[]>,
      ]);
      setOverview(ov);
      const eventList = Array.isArray(ev) ? ev : (ev.events ?? []);
      setEvents(eventList);
      setAllEvidence(Array.isArray(allEv) ? allEv : (allEv.evidence ?? []));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    void refreshEvents();
  }, [refreshEvents]);

  useEffect(() => {
    if (!selectedEventId && events.length) setSelectedEventId(events[0].id);
    if (selectedEventId && events.length && !events.some((e) => e.id === selectedEventId)) {
      setSelectedEventId(events[0].id);
      setSelectedEvidenceKey(null);
    }
  }, [events, selectedEventId]);

  const refreshEvidence = useCallback(async () => {
    if (!taskId || !selectedEventId) {
      setEvidence([]);
      return;
    }
    try {
      const data = (await getEventEvidence(taskId, selectedEventId)) as { evidence?: EvidenceRow[] } | EvidenceRow[];
      setEvidence(Array.isArray(data) ? data : (data.evidence ?? []));
    } catch (err) {
      toast.error(`证据加载失败：${errorMessage(err)}`);
    }
  }, [taskId, selectedEventId, toast]);

  useEffect(() => {
    void refreshEvidence();
  }, [refreshEvidence]);

  const selectedEvent = useMemo(
    () => events.find((e) => e.id === selectedEventId) ?? null,
    [events, selectedEventId],
  );

  const handleCreateEvent = async () => {
    if (!taskId || !newEventTitle.trim()) return;
    setCreatingEvent(true);
    try {
      await createInvestigationEvent(taskId, {
        title: newEventTitle.trim(),
        createdBy: localStorage.getItem('auth_user') || 'analyst',
      });
      setNewEventTitle('');
      toast.success('调查事件已创建');
      await refreshEvents();
    } catch (err) {
      toast.error(`创建失败：${errorMessage(err)}`);
    } finally {
      setCreatingEvent(false);
    }
  };

  const handleCapture = async (evidenceKey: string) => {
    if (!taskId) return;
    try {
      await captureInvestigationSnapshot(taskId, evidenceKey);
      toast.success('证据快照已捕获');
      await refreshEvidence();
    } catch (err) {
      toast.error(`捕获失败：${errorMessage(err)}`);
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<Microscope size={36} />}
          title="二次调查分析工作台"
          description="请先从顶部任务选择器选择一个已完成初次自动分析的任务。"
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card card-pad flex items-center gap-3 text-rose-600">
        <AlertTriangle size={18} />
        <span className="text-sm flex-1">调查工作台加载失败:{error}</span>
        <Button size="sm" onClick={() => void refreshEvents()}>
          重试
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-[1600px]">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-4 text-xs text-ink-500 dark:text-ink-400">
          <span>{overview?.event_count ?? 0} 事件</span>
          <span>{overview?.analysis_count ?? 0} 分析</span>
          <span>{overview?.report_evidence_count ?? 0} 报告证据</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link
            to={`/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic`}
            className="btn-ghost btn-sm"
          >
            最终报告
          </Link>
          <Button size="sm" variant="ghost" onClick={() => void refreshEvents()}>
            <RefreshCw size={13} /> 刷新
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr_1.2fr] gap-4 items-start">
        {/* Events column */}
        <div className="card">
          <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
            <h3 className="card-title">调查事件</h3>
          </div>
          <div className="p-3 border-b border-ink-100 dark:border-ink-800 flex gap-1.5">
            <input
              type="text"
              className="input py-1.5 text-xs flex-1"
              placeholder="新事件标题…"
              value={newEventTitle}
              onChange={(e) => setNewEventTitle(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleCreateEvent()}
            />
            <Button size="sm" variant="primary" onClick={() => void handleCreateEvent()} disabled={creatingEvent || !newEventTitle.trim()}>
              <Plus size={13} />
            </Button>
          </div>
          {loading && events.length === 0 ? (
            <LoadingBlock />
          ) : events.length === 0 ? (
            <EmptyState title="暂无调查事件" />
          ) : (
            <ul className="divide-y divide-ink-100 dark:divide-ink-800 max-h-[520px] overflow-y-auto">
              {events.map((event) => (
                <li key={event.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedEventId(event.id);
                      setSelectedEvidenceKey(null);
                    }}
                    className={cx(
                      'w-full text-left px-4 py-2.5 transition-colors',
                      event.id === selectedEventId
                        ? 'bg-accent-50 dark:bg-accent-500/10'
                        : 'hover:bg-ink-50 dark:hover:bg-ink-900/50',
                    )}
                  >
                    <p className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">{event.title}</p>
                    <p className="text-2xs text-ink-400 mt-0.5">{formatDateTime(event.created_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Evidence column */}
        <div className="card">
          <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800">
            <h3 className="card-title">
              {selectedEvent ? `「${selectedEvent.title}」的证据` : '全部已捕获证据'}
            </h3>
          </div>
          {(() => {
            const rows = selectedEventId ? evidence : allEvidence;
            return rows.length === 0 ? (
              <EmptyState title="暂无证据" description="可从时间线/文件页捕获证据进入调查。" />
            ) : (
              <ul className="divide-y divide-ink-100 dark:divide-ink-800 max-h-[520px] overflow-y-auto">
                {rows.map((ev) => (
                  <li key={ev.evidence_key}>
                    <button
                      type="button"
                      onClick={() => setSelectedEvidenceKey(ev.evidence_key)}
                      className={cx(
                        'w-full text-left px-4 py-2.5 transition-colors',
                        ev.evidence_key === selectedEvidenceKey
                          ? 'bg-accent-50 dark:bg-accent-500/10'
                          : 'hover:bg-ink-50 dark:hover:bg-ink-900/50',
                      )}
                    >
                      <p className="text-xs font-mono text-ink-800 dark:text-ink-100 truncate">{ev.evidence_key}</p>
                      {ev.kind && <p className="text-2xs text-ink-400 mt-0.5">{ev.kind}</p>}
                    </button>
                  </li>
                ))}
              </ul>
            );
          })()}
        </div>

        {/* Detail / analysis column */}
        <EvidenceDetailPanel
          taskId={taskId}
          evidenceKey={selectedEvidenceKey}
          onCapture={handleCapture}
          onChanged={() => {
            void refreshEvents();
            void refreshEvidence();
          }}
        />
      </div>
    </div>
  );
}
