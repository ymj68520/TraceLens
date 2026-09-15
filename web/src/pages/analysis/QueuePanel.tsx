import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileDown,
  Info,
  ListChecks,
  Plus,
  RotateCw,
  X,
  XCircle,
} from 'lucide-react';
import type { ForensicTask } from '../../types/api';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import EmptyState from '../../components/ui/EmptyState';
import { Spinner } from '../../components/ui/Spinner';
import { ProgressBar } from '../../components/ui/ProgressBar';
import { basename, cx } from '../../lib/utils';
import { emitAppEvent } from '../../lib/appEvents';
import type { QueueEntry, QueueItemStatus, TaskResultSnapshot } from './types';
import { shortTaskId } from './exporters';

const STATUS_META: Record<QueueItemStatus, { label: string; tone: 'neutral' | 'accent' | 'success' | 'danger' }> = {
  pending: { label: '等待', tone: 'neutral' },
  running: { label: '进行中', tone: 'accent' },
  done: { label: '完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
};

function StatusIcon({ status }: { status: QueueItemStatus }) {
  if (status === 'running') return <Spinner size="sm" className="shrink-0 mt-0.5" />;
  if (status === 'done') return <CheckCircle2 size={15} className="shrink-0 mt-0.5 text-emerald-500" />;
  if (status === 'failed') return <XCircle size={15} className="shrink-0 mt-0.5 text-rose-500" />;
  return <Clock3 size={15} className="shrink-0 mt-0.5 text-ink-300 dark:text-ink-600" />;
}

interface QueuePanelProps {
  entries: QueueEntry[];
  tasks: ForensicTask[];
  concurrency: number;
  onEnqueueTasks: (taskIds: string[]) => void;
  onRetry: (id: string) => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  onOpenResult: (snapshot: TaskResultSnapshot) => void;
  onExportCSV: (snapshot: TaskResultSnapshot) => void;
}

/** 批量研判队列面板：任务多选入队 + 条目状态 + 移除/重试/清空。 */
export default function QueuePanel({
  entries,
  tasks,
  concurrency,
  onEnqueueTasks,
  onRetry,
  onRemove,
  onClear,
  onOpenResult,
  onExportCSV,
}: QueuePanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const running = entries.filter((e) => e.status === 'running').length;
  const pending = entries.filter((e) => e.status === 'pending').length;
  const done = entries.filter((e) => e.status === 'done').length;
  const failed = entries.filter((e) => e.status === 'failed').length;
  const progress = entries.length === 0 ? 0 : Math.round(((done + failed) / entries.length) * 100);

  // 队列全部完成时发一条通知（与上方汇总一致的成败口径），每次运行只发一次。
  const settledRef = useRef(true);
  useEffect(() => {
    if (pending + running > 0) {
      settledRef.current = false;
      return;
    }
    if (entries.length === 0 || settledRef.current) return;
    settledRef.current = true;
    if (failed === 0) {
      emitAppEvent({ kind: 'success', title: `批量研判完成：${done} 项全部成功` });
    } else {
      emitAppEvent({ kind: 'error', title: `批量研判完成：成功 ${done} 项，失败 ${failed} 项` });
    }
  }, [entries.length, pending, running, done, failed]);

  const toggleTask = (taskId: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const queuedTaskIds = useMemo(
    () => new Set(entries.filter((e) => e.item.kind === 'task').map((e) => (e.item as { taskId: string }).taskId)),
    [entries],
  );

  const submitSelected = () => {
    if (selected.size === 0) return;
    onEnqueueTasks([...selected]);
    setSelected(new Set());
    setPickerOpen(false);
  };

  return (
    <Card padded={false}>
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center gap-1.5">
        <ListChecks size={14} className="text-accent-600 dark:text-accent-400" />
        <h3 className="card-title flex-1">批量研判队列</h3>
        <span className="text-2xs font-mono text-ink-400 tabular-nums">
          {running}/{concurrency} 执行中
        </span>
        {entries.some((e) => e.status !== 'running') && (
          <Button variant="ghost" size="sm" onClick={onClear} className="px-1.5 py-1 text-2xs">
            清空
          </Button>
        )}
      </div>

      {/* 任务选择器 */}
      <div className="px-4 pt-3 pb-2 border-b border-ink-100 dark:border-ink-800/60">
        <button
          type="button"
          onClick={() => setPickerOpen((o) => !o)}
          className="flex w-full items-center gap-1.5 text-xs font-medium text-ink-600 dark:text-ink-300 hover:text-ink-900 dark:hover:text-ink-100 transition-colors"
          aria-expanded={pickerOpen}
        >
          {pickerOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          选择任务加入队列
          {selected.size > 0 && (
            <span className="chip bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20">
              已选 {selected.size}
            </span>
          )}
        </button>
        {pickerOpen && (
          <div className="mt-2">
            {tasks.length === 0 ? (
              <p className="py-2 text-2xs text-ink-400">任务列表为空，请先创建取证任务。</p>
            ) : (
              <>
                <ul className="max-h-44 overflow-y-auto rounded-md border border-ink-200/70 dark:border-ink-800 divide-y divide-ink-100 dark:divide-ink-800/60">
                  {tasks.map((t) => (
                    <li key={t.id} className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-ink-50 dark:hover:bg-ink-900/60 transition-colors">
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 accent-accent-600"
                        checked={selected.has(t.id)}
                        onChange={() => toggleTask(t.id)}
                        aria-label={`选择任务 ${t.id}`}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block text-2xs font-medium text-ink-800 dark:text-ink-200 truncate">
                          {basename(t.image_path) || t.id}
                        </span>
                        <span className="block text-2xs font-mono text-ink-400 truncate">{shortTaskId(t.id)}</span>
                      </span>
                      {queuedTaskIds.has(t.id) && <Badge tone="accent">已在队列</Badge>}
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={submitSelected}
                    disabled={selected.size === 0}
                  >
                    <Plus size={13} /> 加入队列（{selected.size}）
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelected(new Set(tasks.map((t) => t.id)))}
                  >
                    全选
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* 队列条目 */}
      {entries.length === 0 ? (
        <EmptyState
          className="py-10"
          icon={<ListChecks size={28} />}
          title="队列为空"
          description="勾选任务或文件证据加入队列，系统将按并发 2 依次执行研判。"
        />
      ) : (
        <ul className="divide-y divide-ink-100 dark:divide-ink-800/60 max-h-[420px] overflow-y-auto">
          {entries.map((entry) => {
            const meta = STATUS_META[entry.status];
            const item = entry.item;
            const isTask = item.kind === 'task';
            const label = isTask ? item.label : basename(item.filePath);
            const sub = isTask ? item.taskId : item.filePath;
            const snapshot =
              entry.result && entry.result.kind === 'task' ? entry.result.snapshot : null;
            const analysis =
              entry.result && entry.result.kind === 'file' ? entry.result.analysis : null;
            return (
              <li key={entry.id} className="px-4 py-2.5 flex items-start gap-2.5">
                <StatusIcon status={entry.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <Badge tone={isTask ? 'accent' : 'info'}>{isTask ? '任务' : '文件'}</Badge>
                    <span className="text-xs font-medium text-ink-800 dark:text-ink-200 truncate">{label}</span>
                    <Badge tone={meta.tone} dot className="shrink-0">
                      {meta.label}
                    </Badge>
                  </div>
                  <p className="mt-0.5 text-2xs font-mono text-ink-400 truncate" title={sub}>
                    {sub}
                  </p>
                  {entry.status === 'failed' && entry.error && (
                    <p className="mt-1 text-2xs text-rose-500 leading-relaxed">{entry.error}</p>
                  )}
                  {entry.status === 'done' && snapshot && (
                    <p className="mt-1 text-2xs text-ink-500 dark:text-ink-400 tabular-nums">
                      文件 {snapshot.descriptions.length} 项 · 事件簇 {snapshot.clusters.length} 项
                    </p>
                  )}
                  {entry.status === 'done' && analysis?.summary && (
                    <p className="mt-1 text-2xs text-ink-500 dark:text-ink-400 leading-relaxed line-clamp-2">
                      {analysis.summary}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  {entry.status === 'done' && snapshot && (
                    <>
                      <button
                        type="button"
                        onClick={() => onOpenResult(snapshot)}
                        className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                        title="查看研判结果详情"
                      >
                        <Info size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => onExportCSV(snapshot)}
                        className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                        title="导出 CSV"
                      >
                        <FileDown size={14} />
                      </button>
                    </>
                  )}
                  {entry.status === 'failed' && (
                    <button
                      type="button"
                      onClick={() => onRetry(entry.id)}
                      className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                      title="重试"
                    >
                      <RotateCw size={14} />
                    </button>
                  )}
                  {entry.status !== 'running' && (
                    <button
                      type="button"
                      onClick={() => onRemove(entry.id)}
                      className="p-1.5 rounded-md text-ink-400 hover:text-rose-500 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                      title="移除"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* 汇总进度 */}
      {entries.length > 0 && (
        <div className={cx('px-4 py-2.5 border-t border-ink-200 dark:border-ink-800 space-y-1.5')}>
          <ProgressBar value={progress} />
          <p className="text-2xs text-ink-400 tabular-nums">
            共 {entries.length} 项 · 等待 {pending} · 完成 {done} · 失败 {failed}
          </p>
        </div>
      )}
    </Card>
  );
}
