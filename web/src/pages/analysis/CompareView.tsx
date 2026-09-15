import { useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  FileJson,
  FileText,
  FileDown,
  Info,
  Layers,
  Scale,
} from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import EmptyState from '../../components/ui/EmptyState';
import { Segmented } from '../../components/ui/PageScaffold';
import { cx, formatDateTime } from '../../lib/utils';
import { buildClusterDiff, buildFileDiff, isRowRelevant, summarizeDiff } from './diff';
import { snapshotLabel } from './exporters';
import type {
  ClusterRow,
  DiffRowStatus,
  FileDiffRow,
  LlmDescriptionRow,
  TaskResultSnapshot,
} from './types';

type CompareTab = 'files' | 'clusters';

const ROW_STATUS_META: Record<DiffRowStatus, { label: string; tone: 'neutral' | 'warning' | 'info' }> = {
  same: { label: '一致', tone: 'neutral' },
  changed: { label: '差异', tone: 'warning' },
  'only-a': { label: '仅左侧', tone: 'info' },
  'only-b': { label: '仅右侧', tone: 'info' },
};

/** 变化字段块的琥珀高亮；对比视图中唯一的高亮语义。 */
const DIFF_BLOCK = 'bg-amber-50 dark:bg-amber-500/10 ring-1 ring-inset ring-amber-200 dark:ring-amber-500/30';

function RelevanceBadge({ relevant, dim }: { relevant: boolean; dim?: boolean }) {
  if (dim) return <Badge tone="neutral">不相关</Badge>;
  return relevant ? <Badge tone="success">相关</Badge> : <Badge tone="neutral">不相关</Badge>;
}

function MissingCell({ side }: { side: string }) {
  return (
    <div className="rounded-md border border-dashed border-ink-300 dark:border-ink-700 px-3 py-3 text-center text-2xs text-ink-400">
      {side}无该条目
    </div>
  );
}

function FileCell({
  row,
  side,
  diffFields,
  tinted,
}: {
  row: LlmDescriptionRow | null;
  side: string;
  diffFields: Set<string>;
  tinted: boolean;
}) {
  if (!row) return <MissingCell side={side} />;
  const relevant = isRowRelevant(row.is_relevant);
  return (
    <div
      className={cx(
        'rounded-md border px-3 py-2.5 space-y-1.5',
        tinted
          ? 'border-sky-200 bg-sky-50/60 dark:border-sky-500/30 dark:bg-sky-500/10'
          : 'border-ink-200/70 bg-ink-50/50 dark:border-ink-800 dark:bg-ink-900/40',
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-2xs font-semibold text-ink-400 dark:text-ink-500">{side}</span>
        <span className={cx('rounded px-1 py-0.5', diffFields.has('相关性') && DIFF_BLOCK)}>
          <RelevanceBadge relevant={relevant} />
        </span>
      </div>
      <p className={cx('rounded px-1 text-xs leading-relaxed text-ink-700 dark:text-ink-200 line-clamp-4', diffFields.has('摘要') && DIFF_BLOCK)}>
        {row.summary?.trim() || <span className="text-ink-400">（无摘要）</span>}
      </p>
      {(row.keywords?.length ?? 0) > 0 && (
        <div className={cx('flex flex-wrap gap-1 rounded px-1 py-0.5', diffFields.has('关键词') && DIFF_BLOCK)}>
          {row.keywords!.slice(0, 6).map((kw) => (
            <span key={kw} className="chip bg-white text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-300 dark:border-ink-700">
              {kw}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ClusterCell({
  row,
  side,
  diffFields,
  tinted,
}: {
  row: ClusterRow | null;
  side: string;
  diffFields: Set<string>;
  tinted: boolean;
}) {
  if (!row) return <MissingCell side={side} />;
  return (
    <div
      className={cx(
        'rounded-md border px-3 py-2.5 space-y-1.5',
        tinted
          ? 'border-sky-200 bg-sky-50/60 dark:border-sky-500/30 dark:bg-sky-500/10'
          : 'border-ink-200/70 bg-ink-50/50 dark:border-ink-800 dark:bg-ink-900/40',
      )}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-2xs font-semibold text-ink-400 dark:text-ink-500">{side}</span>
        <span className={cx('rounded px-1 py-0.5', diffFields.has('相关性') && DIFF_BLOCK)}>
          <RelevanceBadge relevant={isRowRelevant(row.llm_is_relevant)} />
        </span>
      </div>
      <p className={cx('rounded px-1 text-xs leading-relaxed text-ink-700 dark:text-ink-200 line-clamp-4', diffFields.has('摘要') && DIFF_BLOCK)}>
        {row.llm_summary?.trim() || <span className="text-ink-400">（无摘要）</span>}
      </p>
    </div>
  );
}

function FileDiffRowItem({
  row,
  onOpenRow,
}: {
  row: FileDiffRow;
  onOpenRow: (side: 'a' | 'b', r: LlmDescriptionRow) => void;
}) {
  const diffFields = new Set(row.fields.map((f) => f.label));
  return (
    <div
      className={cx(
        'rounded-lg border px-3 py-2.5',
        row.status === 'changed'
          ? 'border-amber-200 dark:border-amber-500/30'
          : 'border-ink-200/70 dark:border-ink-800',
      )}
    >
      <div className="flex items-center gap-2">
        <FileText size={12} className="shrink-0 text-ink-400" />
        <span className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">{row.name}</span>
        <span className="flex-1 min-w-0 text-2xs font-mono text-ink-400 truncate" title={row.key}>
          {row.key}
        </span>
        <Badge tone={ROW_STATUS_META[row.status].tone} dot>
          {ROW_STATUS_META[row.status].label}
        </Badge>
        {row.a && (
          <button
            type="button"
            onClick={() => onOpenRow('a', row.a!)}
            className="p-1 rounded text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
            title="查看左侧详情"
          >
            <Info size={13} />
          </button>
        )}
        {row.b && (
          <button
            type="button"
            onClick={() => onOpenRow('b', row.b!)}
            className="p-1 rounded text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
            title="查看右侧详情"
          >
            <Info size={13} />
          </button>
        )}
      </div>
      <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
        <FileCell row={row.a} side="左侧" diffFields={diffFields} tinted={row.status === 'only-a'} />
        <FileCell row={row.b} side="右侧" diffFields={diffFields} tinted={row.status === 'only-b'} />
      </div>
    </div>
  );
}

interface CompareViewProps {
  pool: TaskResultSnapshot[];
  onExportCSV: (snapshot: TaskResultSnapshot) => void;
  onExportJSON: (snapshot: TaskResultSnapshot) => void;
  onOpenFile: (taskId: string, row: LlmDescriptionRow) => void;
  onOpenCluster: (taskId: string, row: ClusterRow) => void;
  onGoQueue: () => void;
}

/** 结果对比视图：两列布局、差异高亮、上一对/下一对切换。 */
export default function CompareView({
  pool,
  onExportCSV,
  onExportJSON,
  onOpenFile,
  onOpenCluster,
  onGoQueue,
}: CompareViewProps) {
  const [selA, setSelA] = useState<string | null>(null);
  const [selB, setSelB] = useState<string | null>(null);
  const [tab, setTab] = useState<CompareTab>('files');
  const [onlyDiff, setOnlyDiff] = useState(false);

  const pairs = useMemo(() => {
    const out: [TaskResultSnapshot, TaskResultSnapshot][] = [];
    for (let i = 0; i < pool.length; i += 1) {
      for (let j = i + 1; j < pool.length; j += 1) out.push([pool[i], pool[j]]);
    }
    return out;
  }, [pool]);

  const pair = useMemo(() => {
    if (pool.length < 2) return null;
    const a = pool.find((s) => s.taskId === selA);
    const b = pool.find((s) => s.taskId === selB);
    if (a && b && a.taskId !== b.taskId) return { a, b };
    return { a: pool[0], b: pool[1] };
  }, [pool, selA, selB]);

  const fileRows = useMemo(
    () => (pair ? buildFileDiff(pair.a.descriptions, pair.b.descriptions) : []),
    [pair],
  );
  const clusterRows = useMemo(
    () => (pair ? buildClusterDiff(pair.a.clusters, pair.b.clusters) : []),
    [pair],
  );

  const fileSummary = useMemo(() => summarizeDiff(fileRows), [fileRows]);
  const clusterSummary = useMemo(() => summarizeDiff(clusterRows), [clusterRows]);
  const summary = tab === 'files' ? fileSummary : clusterSummary;
  const visibleFileRows = onlyDiff ? fileRows.filter((r) => r.status !== 'same') : fileRows;
  const visibleClusterRows = onlyDiff ? clusterRows.filter((r) => r.status !== 'same') : clusterRows;
  const visibleCount = tab === 'files' ? visibleFileRows.length : visibleClusterRows.length;

  const pairIdx = pair
    ? pairs.findIndex(([x, y]) => x.taskId === pair.a.taskId && y.taskId === pair.b.taskId)
    : -1;
  const effectiveIdx = pairIdx >= 0 ? pairIdx : 0;

  const stepPair = (dir: 1 | -1) => {
    if (pairs.length < 2) return;
    const next = (effectiveIdx + dir + pairs.length) % pairs.length;
    setSelA(pairs[next][0].taskId);
    setSelB(pairs[next][1].taskId);
  };

  const pickA = (id: string) => {
    setSelA(id);
    if (id === selB) {
      const other = pool.find((s) => s.taskId !== id);
      if (other) setSelB(other.taskId);
    }
  };
  const pickB = (id: string) => {
    setSelB(id);
    if (id === selA) {
      const other = pool.find((s) => s.taskId !== id);
      if (other) setSelA(other.taskId);
    }
  };

  if (pool.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Scale size={28} />}
          title="暂无可对比的研判结果"
          description="先在队列中完成至少两个任务的研判，再回到此处对比结果差异。"
          action={
            <Button variant="primary" size="sm" onClick={onGoQueue}>
              前往研判队列
            </Button>
          }
        />
      </Card>
    );
  }
  if (pool.length < 2 || !pair) {
    return (
      <Card>
        <EmptyState
          icon={<Scale size={28} />}
          title="还需要一个已完成结果"
          description={`当前只有 ${pool.length} 个已完成研判结果，对比至少需要两个。`}
          action={
            <Button variant="primary" size="sm" onClick={onGoQueue}>
              前往研判队列
            </Button>
          }
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* 对比工具栏 */}
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="section-label shrink-0">对比对象</span>
          <select
            className="select w-auto max-w-[240px] py-1 text-xs"
            value={pair.a.taskId}
            onChange={(e) => pickA(e.target.value)}
            aria-label="选择左侧结果"
          >
            {pool.map((s) => (
              <option key={s.taskId} value={s.taskId}>
                {snapshotLabel(s)}
              </option>
            ))}
          </select>
          <span className="text-2xs font-semibold text-ink-400">vs</span>
          <select
            className="select w-auto max-w-[240px] py-1 text-xs"
            value={pair.b.taskId}
            onChange={(e) => pickB(e.target.value)}
            aria-label="选择右侧结果"
          >
            {pool.map((s) => (
              <option key={s.taskId} value={s.taskId}>
                {snapshotLabel(s)}
              </option>
            ))}
          </select>
          <div className="flex items-center gap-0.5">
            <Button variant="ghost" size="sm" onClick={() => stepPair(-1)} disabled={pairs.length < 2} title="上一对">
              <ChevronLeft size={14} /> 上一对
            </Button>
            <span className="px-1 text-2xs font-mono text-ink-400 tabular-nums">
              {effectiveIdx + 1}/{pairs.length}
            </span>
            <Button variant="ghost" size="sm" onClick={() => stepPair(1)} disabled={pairs.length < 2} title="下一对">
              下一对 <ChevronRight size={14} />
            </Button>
          </div>
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'files', label: '文件证据', icon: FileText, count: fileRows.length },
              { value: 'clusters', label: '事件簇', icon: Layers, count: clusterRows.length },
            ]}
          />
          <label className="ml-auto flex cursor-pointer select-none items-center gap-1.5 text-xs text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 accent-accent-600"
              checked={onlyDiff}
              onChange={(e) => setOnlyDiff(e.target.checked)}
            />
            只看差异
          </label>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge tone="warning" dot>差异 {summary.changed}</Badge>
          <Badge tone="info" dot>仅左侧 {summary.onlyA}</Badge>
          <Badge tone="info" dot>仅右侧 {summary.onlyB}</Badge>
          <Badge tone="neutral" dot>一致 {summary.same}</Badge>
        </div>
      </Card>

      {/* 两侧结果概览 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {[pair.a, pair.b].map((snapshot, i) => (
          <Card key={snapshot.taskId} padded={false} className="overflow-hidden">
            <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800 flex items-center gap-2">
              <span
                className={cx(
                  'chip shrink-0',
                  i === 0
                    ? 'bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20'
                    : 'bg-ink-100 text-ink-600 border border-ink-200 dark:bg-ink-800 dark:text-ink-300 dark:border-ink-700',
                )}
              >
                {i === 0 ? '左侧' : '右侧'}
              </span>
              <span className="min-w-0 flex-1 text-xs font-medium text-ink-800 dark:text-ink-100 truncate">
                {snapshotLabel(snapshot)}
              </span>
              <button
                type="button"
                onClick={() => onExportCSV(snapshot)}
                className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                title="导出 CSV"
              >
                <FileDown size={14} />
              </button>
              <button
                type="button"
                onClick={() => onExportJSON(snapshot)}
                className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                title="导出 JSON"
              >
                <FileJson size={14} />
              </button>
            </div>
            <div className="px-4 py-2.5 text-2xs text-ink-500 dark:text-ink-400 space-y-1">
              <p className="font-mono truncate" title={snapshot.taskId}>{snapshot.taskId}</p>
              <p className="tabular-nums">
                文件证据 {snapshot.descriptions.length} 项 · 事件簇 {snapshot.clusters.length} 项 ·{' '}
                完成于 {formatDateTime(snapshot.finishedAt)}
              </p>
            </div>
          </Card>
        ))}
      </div>

      {/* 差异明细 */}
      {visibleCount === 0 ? (
        <Card>
          <EmptyState
            icon={<Scale size={24} />}
            title={onlyDiff ? '当前对比对没有差异' : '暂无可对比条目'}
            description={
              onlyDiff
                ? '两侧研判结果在所比对字段上完全一致。'
                : '两侧结果均未产出可匹配的条目。'
            }
          />
        </Card>
      ) : (
        <div className="space-y-2 max-h-[760px] overflow-y-auto pr-1">
          {tab === 'files'
            ? visibleFileRows.map((row) => (
                <FileDiffRowItem
                  key={row.key}
                  row={row}
                  onOpenRow={(side, r) => {
                    const snapshot = side === 'a' ? pair.a : pair.b;
                    onOpenFile(snapshot.taskId, r);
                  }}
                />
              ))
            : visibleClusterRows.map((row) => {
                const diffFields = new Set(row.fields.map((f) => f.label));
                return (
                  <div
                    key={row.key}
                    className={cx(
                      'rounded-lg border px-3 py-2.5',
                      row.status === 'changed'
                        ? 'border-amber-200 dark:border-amber-500/30'
                        : 'border-ink-200/70 dark:border-ink-800',
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Layers size={12} className="shrink-0 text-ink-400" />
                      <span className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">
                        {row.key}
                      </span>
                      <Badge tone={ROW_STATUS_META[row.status].tone} dot>
                        {ROW_STATUS_META[row.status].label}
                      </Badge>
                      {row.a && (
                        <button
                          type="button"
                          onClick={() => onOpenCluster(pair.a.taskId, row.a!)}
                          className="p-1 rounded text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                          title="查看左侧详情"
                        >
                          <Info size={13} />
                        </button>
                      )}
                      {row.b && (
                        <button
                          type="button"
                          onClick={() => onOpenCluster(pair.b.taskId, row.b!)}
                          className="p-1 rounded text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                          title="查看右侧详情"
                        >
                          <Info size={13} />
                        </button>
                      )}
                    </div>
                    <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
                      <ClusterCell row={row.a} side="左侧" diffFields={diffFields} tinted={row.status === 'only-a'} />
                      <ClusterCell row={row.b} side="右侧" diffFields={diffFields} tinted={row.status === 'only-b'} />
                    </div>
                  </div>
                );
              })}
        </div>
      )}
    </div>
  );
}
