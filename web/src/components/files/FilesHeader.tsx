import { Brain, Database, RefreshCcw, Layers, FileText, HardDriveDownload, FileSpreadsheet, FileSearch } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { FilesTab } from '../../pages/Files';
import { Segmented } from '../ui/PageScaffold';
import Button from '../ui/Button';
import ProgressBar from '../ui/ProgressBar';
import { useTranslation } from '../../hooks/useTranslation';
import type { TranslationKey } from '../../locales/keys';
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

const TABS: { value: FilesTab; labelKey: TranslationKey; icon: LucideIcon }[] = [
  { value: 'largest', labelKey: 'files.header.tab.largest', icon: FileSearch },
  { value: 'extensions', labelKey: 'files.header.tab.extensions', icon: FileSpreadsheet },
  { value: 'office', labelKey: 'files.header.tab.office', icon: FileText },
  { value: 'extract', labelKey: 'files.header.tab.extract', icon: HardDriveDownload },
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
  const { t } = useTranslation();

  return (
    <div className="card card-pad space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          options={TABS.map(({ value, labelKey, icon }) => ({ value, label: t(labelKey), icon }))}
          value={activeTab}
          onChange={onTabChange}
        />

        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <span
            className={cx('chip', llmAvailable
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20'
              : 'bg-ink-100 text-ink-500 border border-ink-200 dark:bg-ink-800 dark:text-ink-400 dark:border-ink-700')}
          >
            <Brain size={11} /> LLM {llmAvailable ? t('files.header.llm_available') : t('files.header.llm_offline')}
          </span>
          <Button
            size="sm"
            variant="primary"
            disabled={selectedCount === 0 || isBatchRunning || !llmAvailable}
            onClick={onStartBatch}
          >
            <Brain size={13} />
            {selectedCount > 0
              ? t('files.header.batch_analyze_count').replace('{n}', String(selectedCount))
              : t('files.header.batch_analyze')}
          </Button>
          <Button
            size="sm"
            disabled={selectedCount === 0}
            onClick={onOpenReanalyze}
          >
            <RefreshCcw size={13} /> {t('files.header.reanalyze')}
          </Button>
          <Button
            size="sm"
            disabled={!graphitiConnected || graphitiIngesting}
            onClick={onIngestGraphiti}
          >
            <Database size={13} />
            {graphitiIngesting ? t('files.header.importing') : t('files.header.import_graph')}
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
            {batchMessage ?? t('files.header.batch_running')}
          </span>
        </div>
      )}
    </div>
  );
}
