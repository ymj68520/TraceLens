import type { KeyboardEvent, MouseEvent } from 'react';
import { Binary, Brain, ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import type { FileRecord } from '../../types/api';
import type { LlmDescription } from '../../pages/Files';
import { basename, cn, cx, formatBytes } from '../../lib/utils';
import {
  formatFileMtime,
  getFilePath,
  getFileExt,
  getFileSize,
  isDeletedFile,
  type FileDensity,
  type FileSortDir,
  type FileSortKey,
} from './fileUtils';

const BINARY_EXTS = new Set(['.dll', '.exe', '.sys', '.so', '.dylib']);

interface FileTableProps {
  files: FileRecord[];
  density: FileDensity;
  sortKey: FileSortKey;
  sortDir: FileSortDir;
  selectedFiles: Set<string>;
  llmResults: Record<string, LlmDescription>;
  llmAnalyzingFiles: Set<string>;
  dllAnalyzingFiles: Set<string>;
  onSortChange: (key: FileSortKey) => void;
  onToggleFile: (path: string) => void;
  onAnalyzeFile: (file: FileRecord) => void;
  onAnalyzeDll: (file: FileRecord) => void;
  onOpenFile: (file: FileRecord) => void;
}

interface SortableHeaderProps {
  label: string;
  colKey: FileSortKey;
  sortKey: FileSortKey;
  sortDir: FileSortDir;
  onSortChange: (key: FileSortKey) => void;
  className?: string;
}

function SortableHeader({ label, colKey, sortKey, sortDir, onSortChange, className }: SortableHeaderProps) {
  const active = sortKey === colKey;
  const Icon = active ? (sortDir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      className={className}
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        onClick={() => onSortChange(colKey)}
        title={active ? `切换为${sortDir === 'asc' ? '降序' : '升序'}` : `按${label}排序`}
        className={cn(
          'inline-flex items-center gap-1 uppercase tracking-wider font-semibold',
          active
            ? 'text-accent-600 dark:text-accent-400'
            : 'text-ink-500 dark:text-ink-400 hover:text-ink-800 dark:hover:text-ink-200 transition-colors',
        )}
      >
        {label}
        <Icon size={12} strokeWidth={active ? 2.4 : 2} className={cx(!active && 'text-ink-300 dark:text-ink-600')} />
      </button>
    </th>
  );
}

/**
 * The file evidence table. Rows open the detail drawer; the checkbox and
 * action cells opt out so row-level actions don't fight row navigation.
 */
export default function FileTable({
  files,
  density,
  sortKey,
  sortDir,
  selectedFiles,
  llmResults,
  llmAnalyzingFiles,
  dllAnalyzingFiles,
  onSortChange,
  onToggleFile,
  onAnalyzeFile,
  onAnalyzeDll,
  onOpenFile,
}: FileTableProps) {
  const compact = density === 'compact';
  const cellPad = compact ? '!py-1.5' : undefined;

  const openFromRow = (file: FileRecord) => () => onOpenFile(file);
  const rowKeyDown = (file: FileRecord) => (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' && e.target === e.currentTarget) onOpenFile(file);
  };
  const stop = (e: MouseEvent<HTMLTableCellElement>) => e.stopPropagation();

  return (
    <div className="overflow-x-auto">
      <table className="table-shell">
        <thead>
          <tr>
            <th className="w-8" />
            <SortableHeader label="文件名" colKey="name" sortKey={sortKey} sortDir={sortDir} onSortChange={onSortChange} />
            <SortableHeader label="大小" colKey="size" sortKey={sortKey} sortDir={sortDir} onSortChange={onSortChange} className="text-right" />
            <SortableHeader label="修改时间" colKey="mtime" sortKey={sortKey} sortDir={sortDir} onSortChange={onSortChange} />
            <th>AI 描述</th>
            <th className="text-right">操作</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => {
            const filePath = getFilePath(file);
            const base = basename(filePath);
            const ext = getFileExt(filePath);
            const desc = llmResults[filePath] ?? llmResults[base];
            const llmBusy = llmAnalyzingFiles.has(filePath);
            const dllBusy = dllAnalyzingFiles.has(filePath);

            return (
              <tr
                key={filePath}
                tabIndex={0}
                className="cursor-pointer"
                title="点击查看文件详情"
                onClick={openFromRow(file)}
                onKeyDown={rowKeyDown(file)}
              >
                <td className={cellPad} onClick={stop}>
                  <input
                    type="checkbox"
                    className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                    checked={selectedFiles.has(filePath)}
                    onChange={() => onToggleFile(filePath)}
                    aria-label={`选择 ${base}`}
                  />
                </td>
                <td className={cn('max-w-[320px]', cellPad)}>
                  <p className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">
                    {base}
                    {isDeletedFile(file) && (
                      <span className="chip ml-1.5 bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/20 align-middle">
                        已删除
                      </span>
                    )}
                  </p>
                  {!compact && (
                    <p className="text-2xs font-mono text-ink-400 dark:text-ink-500 truncate">{filePath}</p>
                  )}
                </td>
                <td className={cn('text-right text-xs font-mono text-ink-600 dark:text-ink-300 whitespace-nowrap tabular-nums', cellPad)}>
                  {formatBytes(getFileSize(file))}
                </td>
                <td className={cn('text-2xs font-mono text-ink-500 dark:text-ink-400 whitespace-nowrap', cellPad)}>
                  {formatFileMtime(file)}
                </td>
                <td className={cn('max-w-[260px]', cellPad)}>
                  {desc ? (
                    <p className="text-2xs text-ink-500 dark:text-ink-400 line-clamp-2" title={desc.description}>
                      {desc.summary || desc.description}
                    </p>
                  ) : (
                    <span className="text-2xs text-ink-300 dark:text-ink-600">—</span>
                  )}
                </td>
                <td className={cellPad} onClick={stop}>
                  <div className="flex items-center justify-end gap-1">
                    <button
                      type="button"
                      disabled={llmBusy}
                      onClick={() => onAnalyzeFile(file)}
                      className="btn-ghost btn-sm text-accent-600 dark:text-accent-400"
                      title="AI 分析该文件"
                    >
                      <Brain size={13} className={llmBusy ? 'animate-pulse' : ''} />
                      {!compact && (llmBusy ? '分析中' : '分析')}
                    </button>
                    {BINARY_EXTS.has(ext) && (
                      <button
                        type="button"
                        disabled={dllBusy}
                        onClick={() => onAnalyzeDll(file)}
                        className="btn-ghost btn-sm text-ink-500 dark:text-ink-400"
                        title="二进制结构分析"
                      >
                        <Binary size={13} className={dllBusy ? 'animate-pulse' : ''} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
