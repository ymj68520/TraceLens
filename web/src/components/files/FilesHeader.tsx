import { Brain, Database, RefreshCcw, Layers, FileText, HardDriveDownload, FileSpreadsheet } from 'lucide-react';
import type { FilesTab } from '../../pages/Files';
import Button from '../ui/Button';
import ProgressBar from '../ui/ProgressBar';
import { cx } from '../../lib/utils';

interface FilesHeaderProps {
  activeTab: FilesTab;
  onTabChange: (tab: FilesTab) => void;
  selectedCount: number;
  isBatchRunning: boolean;
  batchMessage?: string;
  batchProgress?: number;
  llmAvailable: boolean;
  graphitiConnected: boolean;
  graphitiIngesting: boolean;
  onStartBatch: () => void;
  onIngestGraphiti: () => void;
  onOpenReanalyze: () => void;
}

const TABS: { key: FilesTab; label: string; Icon: typeof FileText }[] = [
  { key: 'largest', label: '大文件', Icon: FileText },
  { key: 'extensions', label: '扩展名分析', Icon: FileSpreadsheet },
  { key: 'office', label: 'Office 预览', Icon: FileText },
  { key: 'extract', label: '文件提取', Icon: HardDriveDownload },
];

export default function FilesHeader({
  activeTab,
  onTabChange,
  selectedCount,
  isBatchRunning,
  batchMessage,
  batchProgress,
  llmAvailable,
  graphitiConnected,
  graphitiIngesting,
  onStartBatch,
  onIngestGraphiti,
  onOpenReanalyze,
}: FilesHeaderProps) {
  return (
    <div className="card card-pad space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden">
          {TABS.map(({ key, label, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onTabChange(key)}
              className={cx(
                'px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-colors',
                activeTab === key
                  ? 'bg-accent-600 text-white'
                  : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800',
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <span
            className={cx('chip', llmAvailable ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20' : 'bg-ink-100 text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-400 dark:border-ink-700')}
          >
            <Brain size={11} /> LLM {llmAvailable ? '可用' : '离线'}
          </span>
          <Button
            size="sm"
            variant="primary"
            disabled={selectedCount === 0 || isBatchRunning || !llmAvailable}
            onClick={onStartBatch}
          >
            <Brain size={13} />
            批量 AI 描述{selectedCount > 0 ? `（${selectedCount}）` : ''}
          </Button>
          <Button
            size="sm"
            disabled={selectedCount === 0}
            onClick={onOpenReanalyze}
          >
            <RefreshCcw size={13} /> 二次分析
          </Button>
          <Button
            size="sm"
            disabled={!graphitiConnected || graphitiIngesting}
            onClick={onIngestGraphiti}
          >
            <Database size={13} />
            {graphitiIngesting ? '导入中…' : '导入知识图谱'}
          </Button>
        </div>
      </div>

      {isBatchRunning && (
        <div className="flex items-center gap-3 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/20 rounded-md px-3 py-2">
          <Layers size={14} className="text-accent-600 dark:text-accent-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <ProgressBar value={batchProgress ?? 0} />
          </div>
          <span className="text-2xs text-accent-700 dark:text-accent-300 whitespace-nowrap">
            {batchMessage ?? '批量分析进行中…'}
          </span>
        </div>
      )}
    </div>
  );
}
