import { Virtuoso } from 'react-virtuoso';
import { Brain, ChevronRight, Folder, Clock, Layers, ChevronLeft } from 'lucide-react';
import type { EventCluster } from '../../types/api';
import EmptyState from '../ui/EmptyState';
import { LoadingBlock } from '../ui/Spinner';
import { basename, cx } from '../../lib/utils';
import { useTranslation } from '../../hooks/useTranslation';

interface ClusterListProps {
  clusters: EventCluster[];
  total: number;
  currentPage: number;
  pageSize: number;
  loading: boolean;
  analyzingClusters: Set<string>;
  onPageChange: (page: number) => void;
  onOpenCluster: (cluster: EventCluster) => void;
  onAnalyzeCluster: (cluster: EventCluster) => void;
}

const EVENT_TYPE_STYLE: Record<string, string> = {
  CREATED: 'text-emerald-600 dark:text-emerald-400',
  MODIFIED: 'text-sky-600 dark:text-sky-400',
  DELETED: 'text-rose-600 dark:text-rose-400',
};

const EVENT_TYPE_LABEL: Record<string, string> = {
  CREATED: '创建',
  MODIFIED: '修改',
  DELETED: '删除',
};

const fmtTime = (ts?: number | string) => {
  if (!ts) return '—';
  const n = typeof ts === 'string' ? Number(ts) : ts;
  return new Date(n * 1000).toLocaleString();
};

export default function ClusterList({
  clusters,
  total,
  currentPage,
  pageSize,
  loading,
  analyzingClusters,
  onPageChange,
  onOpenCluster,
  onAnalyzeCluster,
}: ClusterListProps) {
  const { t } = useTranslation();
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (!loading && clusters.length === 0) {
    return (
      <div className="card">
        <EmptyState title={t('timeline.status.empty')} />
      </div>
    );
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="px-5 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between">
        <h3 className="card-title flex items-center gap-1.5">
          <Layers size={14} className="text-ink-400" />
          事件簇
          <span className="text-2xs font-normal text-ink-400">
            {t('timeline.stats.matches')}: {total}
          </span>
        </h3>
        <div className="flex items-center gap-1 text-xs">
          <button
            type="button"
            className="btn-ghost btn-sm"
            disabled={currentPage <= 1}
            onClick={() => onPageChange(currentPage - 1)}
          >
            <ChevronLeft size={14} />
          </button>
          <span className="text-ink-500 dark:text-ink-400 tabular-nums px-1">
            {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            className="btn-ghost btn-sm"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange(currentPage + 1)}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {loading ? (
        <LoadingBlock text={t('timeline.status.loading')} />
      ) : (
        <Virtuoso
          style={{ height: 560 }}
          data={clusters}
          itemContent={(_, cluster) => {
            const key = JSON.stringify(cluster.group_descriptor || null);
            const analyzing = analyzingClusters.has(key);
            const count = cluster.cluster_count ?? cluster.event_count ?? 1;
            const eventType = cluster.group_descriptor?.event_type ?? '';
            return (
              <div
                className="px-5 py-3 border-b border-ink-100 dark:border-ink-800/60 hover:bg-ink-50 dark:hover:bg-ink-900/40 transition-colors cursor-pointer"
                onClick={() => onOpenCluster(cluster)}
              >
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={cx('text-xs font-semibold', EVENT_TYPE_STYLE[eventType] ?? 'text-ink-500')}>
                        {EVENT_TYPE_LABEL[eventType] ?? eventType}
                      </span>
                      <span className="chip bg-ink-100 dark:bg-ink-800 text-ink-600 dark:text-ink-300">
                        {count} {t('timeline.node.items')}
                      </span>
                      <span className="text-2xs text-ink-400 flex items-center gap-1">
                        <Clock size={11} />
                        {fmtTime(cluster.first_seen)} — {fmtTime(cluster.last_seen)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-ink-600 dark:text-ink-300 flex items-center gap-1 truncate">
                      <Folder size={12} className="shrink-0 text-ink-400" />
                      <span className="truncate font-mono">
                        {cluster.group_descriptor?.parent_directory || '/'}
                      </span>
                    </p>
                    {cluster.llm_summary && (
                      <p className="mt-1.5 text-xs text-ink-500 dark:text-ink-400 line-clamp-2 leading-relaxed">
                        {cluster.llm_summary}
                      </p>
                    )}
                    {cluster.sample_files && cluster.sample_files.length > 0 && (
                      <p className="mt-1 text-2xs text-ink-400 truncate">
                        {t('timeline.node.sample')}: {basename(String(cluster.sample_files[0]))}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    {!cluster.llm_summary && (
                      <button
                        type="button"
                        disabled={analyzing}
                        onClick={(e) => {
                          e.stopPropagation();
                          void onAnalyzeCluster(cluster);
                        }}
                        className="btn-ghost btn-sm text-accent-600 dark:text-accent-400"
                        title="AI 分析该事件簇"
                      >
                        <Brain size={14} className={analyzing ? 'animate-pulse' : ''} />
                        {analyzing ? '分析中' : 'AI 分析'}
                      </button>
                    )}
                    <ChevronRight size={15} className="text-ink-300 dark:text-ink-600" />
                  </div>
                </div>
              </div>
            );
          }}
        />
      )}
    </div>
  );
}
