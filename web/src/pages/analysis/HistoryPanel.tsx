import { History, RotateCcw, Trash2, X } from 'lucide-react';
import Card from '../../components/ui/Card';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import { basename, formatRelativeTime } from '../../lib/utils';
import type { AnalysisHistoryEntry } from './types';
import { shortTaskId } from './exporters';

interface HistoryPanelProps {
  entries: AnalysisHistoryEntry[];
  onRefill: (entry: AnalysisHistoryEntry) => void;
  onRemove: (taskId: string) => void;
  onClear: () => void;
}

/** 最近研判历史：localStorage 持久化（最近 20 条），支持一键回填队列。 */
export default function HistoryPanel({ entries, onRefill, onRemove, onClear }: HistoryPanelProps) {
  return (
    <Card padded={false}>
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center gap-1.5">
        <History size={14} className="text-ink-400" />
        <h3 className="card-title flex-1">最近研判</h3>
        <span className="text-2xs font-mono text-ink-400 tabular-nums">{entries.length}/20</span>
        {entries.length > 0 && (
          <Button variant="ghost" size="sm" onClick={onClear} className="px-1.5 py-1 text-2xs">
            清空
          </Button>
        )}
      </div>

      {entries.length === 0 ? (
        <EmptyState
          className="py-8"
          icon={<History size={24} />}
          title="暂无历史记录"
          description="任务研判完成后会自动记录在此，可一键回填队列。"
        />
      ) : (
        <ul className="divide-y divide-ink-100 dark:divide-ink-800/60 max-h-[300px] overflow-y-auto">
          {entries.map((entry) => (
            <li key={entry.taskId} className="px-4 py-2.5 flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-ink-800 dark:text-ink-200 truncate">
                  {basename(entry.imagePath) || entry.taskId}
                </p>
                <p className="mt-0.5 text-2xs font-mono text-ink-400 truncate">{shortTaskId(entry.taskId)}</p>
                <p className="mt-1 text-2xs text-ink-400 tabular-nums">
                  文件 {entry.fileCount} · 簇 {entry.clusterCount} · {formatRelativeTime(entry.savedAt)}
                </p>
              </div>
              <div className="flex items-center gap-0.5 shrink-0">
                <button
                  type="button"
                  onClick={() => onRefill(entry)}
                  className="p-1.5 rounded-md text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                  title="回填到队列"
                >
                  <RotateCcw size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => onRemove(entry.taskId)}
                  className="p-1.5 rounded-md text-ink-400 hover:text-rose-500 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors"
                  title="删除记录"
                >
                  <X size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {entries.length > 0 && (
        <p className="px-4 py-2 border-t border-ink-100 dark:border-ink-800/60 text-2xs text-ink-400 flex items-center gap-1">
          <Trash2 size={11} className="shrink-0" />
          回填按队列去重规则执行，已完成条目不会重复研判。
        </p>
      )}
    </Card>
  );
}
