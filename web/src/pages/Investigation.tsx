import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, FileSearch, Microscope, Plus, RefreshCw } from 'lucide-react';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import Badge from '../components/ui/Badge';
import { Spinner } from '../components/ui/Spinner';
import { PageHeader, SkeletonBlock, StatStrip } from '../components/ui/PageScaffold';
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
import { emitAppEvent } from '../lib/appEvents';
import { useUrlState } from '../hooks/useUrlState';
import EvidenceDetailPanel from '../components/investigation/EvidenceDetailPanel';
import EvidenceListPanel, { type EvidenceRow } from './investigation/EvidenceListPanel';
import EvidenceDetailDrawer from './investigation/EvidenceDetailDrawer';
import ClueNotesPanel from './investigation/ClueNotesPanel';
import { useClueNotes } from './investigation/useClueNotes';

interface InvEvent {
  id: string;
  title: string;
  summary?: string;
  created_at?: string;
  status?: string;
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
  const [drawerRow, setDrawerRow] = useState<EvidenceRow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEventTitle, setNewEventTitle] = useState('');
  const [creatingEvent, setCreatingEvent] = useState(false);

  // 证据类型过滤持久化到 URL，便于分享与刷新还原。
  const [etype, setEtype] = useUrlState('etype', 'all');

  const clueNotes = useClueNotes(taskId);

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

  const handleCapture = useCallback(
    async (evidenceKey: string) => {
      if (!taskId) return;
      try {
        await captureInvestigationSnapshot(taskId, evidenceKey);
        toast.success('证据快照已捕获');
        await refreshEvidence();
      } catch (err) {
        toast.error(`捕获失败：${errorMessage(err)}`);
      }
    },
    [taskId, refreshEvidence, toast],
  );

  // 证据条目点击：选中（驱动中间分析面板与笔记关联）并打开 Drawer 详情。
  const handleSelectEvidence = useCallback((row: EvidenceRow) => {
    setSelectedEvidenceKey(row.evidence_key);
    setDrawerRow(row);
  }, []);

  const handleAddNote = useCallback(
    (content: string, evidenceKey: string | null) => {
      const ok = clueNotes.addNote(content, evidenceKey);
      if (ok) toast.success('笔记已保存');
      return ok;
    },
    [clueNotes, toast],
  );

  const handleRemoveNote = useCallback(
    (id: string) => {
      clueNotes.removeNote(id);
      toast.info('笔记已删除');
    },
    [clueNotes, toast],
  );

  const handleExportNotes = useCallback((): boolean => {
    const ok = clueNotes.exportNotes();
    if (ok) {
      toast.success('笔记已导出为 JSON');
      emitAppEvent({ kind: 'info', title: '已导出调查笔记' });
    }
    return ok;
  }, [clueNotes, toast]);

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
    <div className="space-y-4">
      <PageHeader
        icon={FileSearch}
        tone="amber"
        title="调查工作台"
        subtitle="多维关联调查与线索整理"
        actions={
          <>
            <Link to={`/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic`} className="btn-ghost btn-sm">
              最终报告
            </Link>
            <Button size="sm" variant="ghost" onClick={() => void refreshEvents()}>
              <RefreshCw size={13} /> 刷新
            </Button>
          </>
        }
      />

      <StatStrip
        stats={[
          { label: '调查事件', value: overview?.event_count ?? events.length },
          { label: '二次分析', value: overview?.analysis_count ?? 0 },
          { label: '报告证据', value: overview?.report_evidence_count ?? 0 },
          { label: '证据条目', value: allEvidence.length },
          { label: '线索笔记', value: clueNotes.notes.length },
        ]}
      />

      <div className="grid grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)_330px] gap-4 items-stretch xl:h-[calc(100vh-13.5rem)] xl:min-h-[560px]">
        {/* 左栏：证据/实体清单 */}
        <EvidenceListPanel
          rows={allEvidence}
          loading={loading}
          selectedKey={selectedEvidenceKey}
          etype={etype}
          onEtypeChange={setEtype}
          onSelect={handleSelectEvidence}
        />

        {/* 中栏：调查事件 + 证据详情/二次分析主视图 */}
        <div className="flex flex-col gap-4 min-w-0 min-h-0 xl:overflow-y-auto pr-0.5">
          <div className="card">
            <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <h3 className="card-title">调查事件</h3>
                <Badge tone="neutral">{events.length}</Badge>
                {selectedEvent && (
                  <Badge tone="accent" className="ml-1">
                    已关联 {evidence.length} 证据
                  </Badge>
                )}
              </div>
              {selectedEvent && (
                <span className="text-2xs text-ink-400 font-mono hidden sm:block">{formatDateTime(selectedEvent.created_at)}</span>
              )}
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
              <Button
                size="sm"
                variant="primary"
                onClick={() => void handleCreateEvent()}
                disabled={creatingEvent || !newEventTitle.trim()}
              >
                {creatingEvent ? <Spinner size="sm" /> : <Plus size={13} />}
              </Button>
            </div>

            {loading && events.length === 0 ? (
              <div className="p-3 space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <SkeletonBlock key={i} className="h-7 w-full" />
                ))}
              </div>
            ) : events.length === 0 ? (
              <EmptyState title="暂无调查事件" description="输入标题创建第一个调查事件。" className="py-8" />
            ) : (
              <div className="p-3 flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                {events.map((event) => {
                  const active = event.id === selectedEventId;
                  return (
                    <button
                      key={event.id}
                      type="button"
                      onClick={() => {
                        setSelectedEventId(event.id);
                        setSelectedEvidenceKey(null);
                      }}
                      title={`${event.title} · ${formatDateTime(event.created_at)}`}
                      className={cx(
                        'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-2xs max-w-[220px] transition-colors',
                        active
                          ? 'border-accent-300 bg-accent-50 text-accent-800 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-200'
                          : 'border-ink-200 bg-white text-ink-600 hover:border-ink-300 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-300 dark:hover:border-ink-600',
                      )}
                    >
                      <span className="truncate">{event.title}</span>
                      {event.status && (
                        <span className={cx('shrink-0 text-2xs font-mono', active ? 'text-accent-600 dark:text-accent-400' : 'text-ink-400')}>
                          {event.status}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

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

        {/* 右栏：线索笔记 */}
        <ClueNotesPanel
          notes={clueNotes.notes}
          linkedEvidenceKey={selectedEvidenceKey}
          onAdd={handleAddNote}
          onRemove={handleRemoveNote}
          onExport={handleExportNotes}
        />
      </div>

      <EvidenceDetailDrawer
        taskId={taskId}
        evidence={drawerRow}
        onClose={() => setDrawerRow(null)}
        onCapture={handleCapture}
      />
    </div>
  );
}
