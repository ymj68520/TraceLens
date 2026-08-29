import { Search, X } from 'lucide-react';
import type { EventCluster } from '../../types/api';
import { LoadingBlock } from '../ui/Spinner';
import EmptyState from '../ui/EmptyState';
import { basename, formatBytes } from '../../lib/utils';

export interface ClusterDetailEvent {
  timestamp?: number | string;
  event_type?: string;
  file_path?: string;
  file_size?: number | string;
  [key: string]: unknown;
}

interface ClusterDetailDrawerProps {
  cluster: EventCluster | null;
  events: ClusterDetailEvent[];
  loading: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  onClose: () => void;
}

const fmtTime = (ts?: number | string) => {
  if (!ts) return '—';
  const n = typeof ts === 'string' ? Number(ts) : ts;
  return new Date(n * 1000).toLocaleString();
};

export default function ClusterDetailDrawer({
  cluster,
  events,
  loading,
  search,
  onSearchChange,
  onClose,
}: ClusterDetailDrawerProps) {
  if (!cluster) return null;

  const descriptor = cluster.group_descriptor;

  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink-950/40 animate-fade-in" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 w-full max-w-xl bg-white dark:bg-ink-925 border-l border-ink-200 dark:border-ink-800 shadow-drawer flex flex-col animate-slide-in-right">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-ink-200 dark:border-ink-800">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-100">事件簇详情</h2>
            <p className="text-2xs text-ink-500 dark:text-ink-400 font-mono truncate mt-0.5">
              {descriptor?.event_type} · {descriptor?.parent_directory || '/'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-ink-400 hover:text-ink-600 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
            aria-label="关闭"
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-3 border-b border-ink-100 dark:border-ink-800">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="input pl-8 text-xs"
              placeholder="在簇内搜索文件路径…"
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <LoadingBlock text="加载事件…" />
          ) : events.length === 0 ? (
            <EmptyState title="该簇内没有匹配的事件" />
          ) : (
            <table className="table-shell">
              <thead className="sticky top-0 bg-white dark:bg-ink-925">
                <tr>
                  <th>时间</th>
                  <th>文件</th>
                  <th className="text-right">大小</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev, idx) => (
                  <tr key={idx}>
                    <td className="whitespace-nowrap font-mono text-2xs text-ink-500">
                      {fmtTime(ev.timestamp)}
                    </td>
                    <td className="max-w-[260px]">
                      <p className="text-xs truncate font-mono" title={ev.file_path}>
                        {basename(ev.file_path)}
                      </p>
                      <p className="text-2xs text-ink-400 truncate font-mono">{ev.file_path}</p>
                    </td>
                    <td className="text-right text-2xs text-ink-500 whitespace-nowrap">
                      {formatBytes(Number(ev.file_size))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-5 py-2.5 border-t border-ink-200 dark:border-ink-800 text-2xs text-ink-400">
          共 {events.length} 条事件
        </div>
      </aside>
    </>
  );
}
