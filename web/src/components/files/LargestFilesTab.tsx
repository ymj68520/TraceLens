import { Brain, Binary } from 'lucide-react';
import type { FileRecord } from '../../types/api';
import type { LlmDescription } from '../../pages/Files';
import { LoadingBlock } from '../ui/Spinner';
import EmptyState from '../ui/EmptyState';
import { basename, formatBytes, cx } from '../../lib/utils';

interface LargestFilesTabProps {
  files: FileRecord[];
  loading: boolean;
  error: string | null;
  selectedFiles: Set<string>;
  llmResults: Record<string, LlmDescription>;
  llmAnalyzingFiles: Set<string>;
  dllAnalyzingFiles: Set<string>;
  onToggleFile: (path: string) => void;
  onAnalyzeFile: (file: FileRecord) => void;
  onAnalyzeDll: (file: FileRecord) => void;
  filterExtension: string;
  filterMinSize: string;
  filterMaxSize: string;
  onFilterExtension: (v: string) => void;
  onFilterMinSize: (v: string) => void;
  onFilterMaxSize: (v: string) => void;
}

const BINARY_EXTS = new Set(['.dll', '.exe', '.sys', '.so', '.dylib']);

export default function LargestFilesTab({
  files,
  loading,
  error,
  selectedFiles,
  llmResults,
  llmAnalyzingFiles,
  dllAnalyzingFiles,
  onToggleFile,
  onAnalyzeFile,
  onAnalyzeDll,
  filterExtension,
  filterMinSize,
  filterMaxSize,
  onFilterExtension,
  onFilterMinSize,
  onFilterMaxSize,
}: LargestFilesTabProps) {
  if (loading) return <LoadingBlock text="正在加载文件…" />;
  if (error) return <EmptyState title="加载失败" description={error} />;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-ink-200 dark:border-ink-800">
        <input
          type="text"
          className="input w-36 py-1.5 text-xs"
          placeholder="扩展名（如 .exe）"
          value={filterExtension}
          onChange={(e) => onFilterExtension(e.target.value)}
        />
        <input
          type="number"
          className="input w-28 py-1.5 text-xs"
          placeholder="最小 MB"
          value={filterMinSize}
          onChange={(e) => onFilterMinSize(e.target.value)}
        />
        <input
          type="number"
          className="input w-28 py-1.5 text-xs"
          placeholder="最大 MB"
          value={filterMaxSize}
          onChange={(e) => onFilterMaxSize(e.target.value)}
        />
        <span className="text-2xs text-ink-400 ml-auto">
          {files.length} 个文件，已选 {selectedFiles.size}
        </span>
      </div>

      {files.length === 0 ? (
        <EmptyState title="没有符合条件的文件" />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-shell">
            <thead>
              <tr>
                <th className="w-8" />
                <th>文件</th>
                <th className="text-right">大小</th>
                <th>AI 描述</th>
                <th className="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const filePath = ((file.path as string) || file.file_path) ?? '';
                const base = basename(filePath);
                const desc = llmResults[filePath] ?? llmResults[base];
                const ext = base.includes('.') ? `.${base.split('.').pop()!.toLowerCase()}` : '';
                const isBinary = BINARY_EXTS.has(ext);
                const llmBusy = llmAnalyzingFiles.has(filePath);
                const dllBusy = dllAnalyzingFiles.has(filePath);
                const size = Number(file.file_size ?? file.size ?? 0);

                return (
                  <tr key={filePath}>
                    <td>
                      <input
                        type="checkbox"
                        className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                        checked={selectedFiles.has(filePath)}
                        onChange={() => onToggleFile(filePath)}
                        aria-label={`选择 ${base}`}
                      />
                    </td>
                    <td className="max-w-[320px]">
                      <p className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate" title={filePath}>
                        {base}
                      </p>
                      <p className="text-2xs font-mono text-ink-400 truncate">{filePath}</p>
                    </td>
                    <td className="text-right text-xs font-mono text-ink-600 dark:text-ink-300 whitespace-nowrap">
                      {formatBytes(size)}
                    </td>
                    <td className="max-w-[280px]">
                      {desc ? (
                        <p className="text-2xs text-ink-500 dark:text-ink-400 line-clamp-2" title={desc.description}>
                          {desc.summary || desc.description}
                        </p>
                      ) : (
                        <span className="text-2xs text-ink-300 dark:text-ink-600">—</span>
                      )}
                    </td>
                    <td>
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          disabled={llmBusy}
                          onClick={() => onAnalyzeFile(file)}
                          className={cx('btn-ghost btn-sm text-accent-600 dark:text-accent-400')}
                          title="AI 分析该文件"
                        >
                          <Brain size={13} className={llmBusy ? 'animate-pulse' : ''} />
                          {llmBusy ? '分析中' : '分析'}
                        </button>
                        {isBinary && (
                          <button
                            type="button"
                            disabled={dllBusy}
                            onClick={() => onAnalyzeDll(file)}
                            className="btn-ghost btn-sm text-ink-500"
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
      )}
    </div>
  );
}
