import { useMemo } from 'react';
import { AlertTriangle, Download, FilterX, FolderSearch, Rows2, Rows3, SearchX } from 'lucide-react';
import type { FileRecord } from '../../types/api';
import type { LlmDescription } from '../../pages/Files';
import Button from '../ui/Button';
import EmptyState from '../ui/EmptyState';
import { Segmented, SkeletonTable, StatStrip, type StatItem } from '../ui/PageScaffold';
import FileTable from './FileTable';
import { useTranslation } from '../../hooks/useTranslation';
import type { TranslationKey } from '../../locales/keys';
import { getFileExt, getFilePath, type FileDensity, type FileSortDir, type FileSortKey } from './fileUtils';

interface LargestFilesTabProps {
  /** Filtered + sorted rows — what the table and the CSV export show. */
  files: FileRecord[];
  /** Unfiltered rows — source for the extension stat chips. */
  allFiles: FileRecord[];
  loading: boolean;
  error: string | null;
  density: FileDensity;
  sortKey: FileSortKey;
  sortDir: FileSortDir;
  selectedFiles: Set<string>;
  llmResults: Record<string, LlmDescription>;
  llmAnalyzingFiles: Set<string>;
  dllAnalyzingFiles: Set<string>;
  filterExtension: string;
  filterMinSize: string;
  filterMaxSize: string;
  onSortChange: (key: FileSortKey) => void;
  onDensityChange: (d: FileDensity) => void;
  onFilterExtension: (v: string) => void;
  onFilterMinSize: (v: string) => void;
  onFilterMaxSize: (v: string) => void;
  onClearFilters: () => void;
  onToggleFile: (path: string) => void;
  onAnalyzeFile: (file: FileRecord) => void;
  onAnalyzeDll: (file: FileRecord) => void;
  onOpenFile: (file: FileRecord) => void;
  onRetry: () => void;
  onExportCsv: () => void;
}

const DENSITY_OPTIONS: { value: FileDensity; labelKey: TranslationKey; icon: typeof Rows2 }[] = [
  { value: 'compact', labelKey: 'files.header.density_compact', icon: Rows3 },
  { value: 'comfortable', labelKey: 'files.header.density_comfortable', icon: Rows2 },
];

export default function LargestFilesTab({
  files,
  allFiles,
  loading,
  error,
  density,
  sortKey,
  sortDir,
  selectedFiles,
  llmResults,
  llmAnalyzingFiles,
  dllAnalyzingFiles,
  filterExtension,
  filterMinSize,
  filterMaxSize,
  onSortChange,
  onDensityChange,
  onFilterExtension,
  onFilterMinSize,
  onFilterMaxSize,
  onClearFilters,
  onToggleFile,
  onAnalyzeFile,
  onAnalyzeDll,
  onOpenFile,
  onRetry,
  onExportCsv,
}: LargestFilesTabProps) {
  const { t } = useTranslation();
  const hasFilters = Boolean(filterExtension || filterMinSize || filterMaxSize);

  // Top 5 extensions by count across the whole (unfiltered) result set, so
  // the chips stay stable while filters are being applied.
  const extChips = useMemo<StatItem[]>(() => {
    if (allFiles.length === 0) return [];
    const counts = new Map<string, number>();
    allFiles.forEach((f) => {
      const ext = getFileExt(getFilePath(f));
      counts.set(ext, (counts.get(ext) ?? 0) + 1);
    });
    const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
    return [
      {
        label: t('common.all'),
        value: allFiles.length,
        active: !filterExtension,
        onClick: () => onFilterExtension(''),
      },
      ...top.map(([ext, count]) => ({
        label: ext || t('files.header.no_extension'),
        value: count,
        active: filterExtension === ext,
        onClick: () => onFilterExtension(filterExtension === ext ? '' : ext),
      })),
    ];
  }, [allFiles, filterExtension, onFilterExtension, t]);

  return (
    <div>
      {/* Toolbar: filters · count · density · export */}
      <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-b border-ink-200 dark:border-ink-800">
        <input
          type="text"
          className="input w-36 py-1.5 text-xs"
          placeholder={t('files.header.filter_ext_placeholder')}
          value={filterExtension}
          onChange={(e) => onFilterExtension(e.target.value)}
        />
        <input
          type="number"
          className="input w-24 py-1.5 text-xs"
          placeholder={t('files.header.filter_min_mb')}
          value={filterMinSize}
          onChange={(e) => onFilterMinSize(e.target.value)}
        />
        <input
          type="number"
          className="input w-24 py-1.5 text-xs"
          placeholder={t('files.header.filter_max_mb')}
          value={filterMaxSize}
          onChange={(e) => onFilterMaxSize(e.target.value)}
        />
        {hasFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="btn-ghost btn-sm text-ink-500 dark:text-ink-400"
            title={t('files.header.clear_filters_title')}
          >
            <FilterX size={13} /> {t('common.clear_filters')}
          </button>
        )}

        <div className="ml-auto flex items-center gap-2 flex-wrap">
          <span className="text-2xs text-ink-400 dark:text-ink-500 whitespace-nowrap">
            {files.length === allFiles.length
              ? t('files.header.count_total').replace('{n}', String(files.length))
              : t('files.header.count_filtered')
                  .replace('{n}', String(files.length))
                  .replace('{m}', String(allFiles.length))}
            {selectedFiles.size > 0 &&
              ` · ${t('files.header.selected').replace('{n}', String(selectedFiles.size))}`}
          </span>
          <Segmented
            options={DENSITY_OPTIONS.map(({ value, labelKey, icon: Icon }) => ({ value, label: t(labelKey), icon: Icon }))}
            value={density}
            onChange={onDensityChange}
          />
          <Button size="sm" onClick={onExportCsv} disabled={files.length === 0} title={t('files.header.export_csv_title')}>
            <Download size={13} /> {t('files.header.export_csv')}
          </Button>
        </div>
      </div>

      {/* Extension stat chips */}
      {extChips.length > 0 && (
        <div className="px-5 py-2.5 border-b border-ink-200 dark:border-ink-800">
          <StatStrip stats={extChips} />
        </div>
      )}

      {/* Data states */}
      {loading ? (
        <SkeletonTable rows={8} cols={5} />
      ) : error ? (
        <EmptyState
          icon={<AlertTriangle size={36} />}
          title={t('files.list.load_failed')}
          description={error}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : allFiles.length === 0 ? (
        <EmptyState
          icon={<FolderSearch size={36} />}
          title={t('files.list.empty.title')}
          description={t('files.list.empty.desc')}
          action={
            <Button variant="secondary" size="sm" onClick={onRetry}>
              {t('common.refresh')}
            </Button>
          }
        />
      ) : files.length === 0 ? (
        <EmptyState
          icon={<SearchX size={36} />}
          title={t('files.list.empty_filtered.title')}
          description={t('files.list.empty_filtered.desc')}
          action={
            <Button variant="secondary" size="sm" onClick={onClearFilters}>
              {t('common.clear_filters')}
            </Button>
          }
        />
      ) : (
        <FileTable
          files={files}
          density={density}
          sortKey={sortKey}
          sortDir={sortDir}
          selectedFiles={selectedFiles}
          llmResults={llmResults}
          llmAnalyzingFiles={llmAnalyzingFiles}
          dllAnalyzingFiles={dllAnalyzingFiles}
          onSortChange={onSortChange}
          onToggleFile={onToggleFile}
          onAnalyzeFile={onAnalyzeFile}
          onAnalyzeDll={onAnalyzeDll}
          onOpenFile={onOpenFile}
        />
      )}
    </div>
  );
}
