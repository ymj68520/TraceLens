import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks } from '../store/taskSlice';
import {
  setBatchJob,
  updateBatchProgress,
  clearBatchJob,
  setRefreshFlag,
} from '../store/intelligenceSlice';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';
import {
  analyzeContent,
  analyzeDLL,
  startBatchAnalysis,
  pollBatchStatus,
  getLLMStatus,
} from '../services/llmService';
import { reanalyzeFiles } from '../services/caseAnalysisService';
import { ingestTaskData, getGraphitiStatus } from '../services/graphitiService';
import type { FileRecord } from '../types/api';
import { useToast } from '../components/ui/Toast';
import EmptyState from '../components/ui/EmptyState';
import Card from '../components/ui/Card';
import { downloadCSV } from '../lib/exportUtils';
import { emitAppEvent } from '../lib/appEvents';
import { basename, errorMessage, formatBytes, formatDateTime } from '../lib/utils';
import { useUrlState } from '../hooks/useUrlState';
import { useTranslation } from '../hooks/useTranslation';
import { FolderOpen } from 'lucide-react';
import { PageHeader } from '../components/ui/PageScaffold';
import FilesHeader from '../components/files/FilesHeader';
import LargestFilesTab from '../components/files/LargestFilesTab';
import ExtensionsTab from '../components/files/ExtensionsTab';
import ExtractionPanel from '../components/files/ExtractionPanel';
import OfficePreviewTab from '../components/files/OfficePreviewTab';
import ReanalyzeModal from '../components/files/ReanalyzeModal';
import FileDetailDrawer from '../components/files/FileDetailDrawer';
import {
  formatSortSpec,
  getFileExt,
  getFileMtimeMs,
  getFilePath,
  getFileSize,
  isDeletedFile,
  parseSortSpec,
  type FileDensity,
  type FileSortKey,
} from '../components/files/fileUtils';

export type FilesTab = 'largest' | 'extensions' | 'office' | 'extract';

const FILES_TABS: FilesTab[] = ['largest', 'extensions', 'office', 'extract'];

export interface LlmDescription {
  summary?: string;
  description?: string;
  keywords?: string[];
  model?: string;
  timestamp?: string;
}

type LlmServiceStatus = { status?: string } | null;
type GraphitiStatus = { status?: string; neo4j_connected?: boolean } | null;

export default function Files() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const dispatch = useAppDispatch();
  const toast = useToast();
  const { t } = useTranslation();

  const { tasks } = useAppSelector((state) => state.tasks);
  const { activeBatchJobs } = useAppSelector((state) => state.intelligence);

  const activeBatch = taskId ? activeBatchJobs[taskId] : undefined;
  const isBatchRunning = activeBatch?.status === 'running';

  useEffect(() => {
    if (taskId && tasks.length === 0) {
      void dispatch(fetchTasks({}));
    }
  }, [taskId, tasks.length, dispatch]);

  // View state persisted to the URL so table views survive reloads and
  // can be shared as links (falling back to sensible defaults).
  const [tabParam, setTabParam] = useUrlState('tab', 'largest');
  const [sortParam, setSortParam] = useUrlState('sort', 'size-desc');
  const [densityParam, setDensityParam] = useUrlState('density', 'comfortable');
  const [filterExtension, setFilterExtension] = useUrlState('ext', '');
  const [filterMinSize, setFilterMinSize] = useUrlState('min', '');
  const [filterMaxSize, setFilterMaxSize] = useUrlState('max', '');

  const activeTab: FilesTab = (FILES_TABS as string[]).includes(tabParam)
    ? (tabParam as FilesTab)
    : 'largest';
  const { key: sortKey, dir: sortDir } = parseSortSpec(sortParam);
  const density: FileDensity = densityParam === 'compact' ? 'compact' : 'comfortable';

  const [largestFiles, setLargestFiles] = useState<FileRecord[]>([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [detailFile, setDetailFile] = useState<FileRecord | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());

  const [llmStatus, setLlmStatus] = useState<LlmServiceStatus>(null);
  const [llmAnalyzingFiles, setLlmAnalyzingFiles] = useState<Set<string>>(new Set());
  const [dllAnalyzingFiles, setDllAnalyzingFiles] = useState<Set<string>>(new Set());
  const [llmResults, setLlmResults] = useState<Record<string, LlmDescription>>({});
  const [graphitiStatus, setGraphitiStatus] = useState<GraphitiStatus>(null);
  const [graphitiIngesting, setGraphitiIngesting] = useState(false);

  const [showReanalyzeModal, setShowReanalyzeModal] = useState(false);
  const [reanalyzing, setReanalyzing] = useState(false);

  const currentTask = tasks.find((t) => t.id === taskId);

  const startBatchPolling = useCallback(
    async (jobId: string) => {
      try {
        const finalStatus = await pollBatchStatus(
          jobId,
          (status) => {
            const processed = (status.files_processed as number) || 0;
            const total = (status.files_total as number) || 1;
            dispatch(
              updateBatchProgress({
                taskId: taskId!,
                progress: Math.round((processed / total) * 100),
                message: (status.message as string) || t('files.batch.analyzing').replace('{processed}', String(processed)).replace('{total}', String(total)),
              }),
            );
          },
          2000,
        );

        const results = (finalStatus as { results?: { file_path?: string; analysis?: LlmDescription }[] }).results;
        if (results) {
          const newDesc: Record<string, LlmDescription> = {};
          results.forEach((r) => {
            if (r.file_path && r.analysis) {
              newDesc[r.file_path] = {
                summary: r.analysis.summary || r.analysis.description?.substring(0, 200),
                description: r.analysis.description,
                keywords: r.analysis.keywords || [],
              };
            }
          });
          setLlmResults((prev) => ({ ...prev, ...newDesc }));
          dispatch(setRefreshFlag({ type: 'files' }));
        }

        dispatch(updateBatchProgress({ taskId: taskId!, status: 'completed', message: t('files.batch.completed') }));
        emitAppEvent({
          kind: 'success',
          title: t('files.batch.event_title'),
          detail: t('files.batch.event_detail').replace('{n}', String(results?.length ?? 0)),
        });
        setTimeout(() => dispatch(clearBatchJob({ taskId: taskId! })), 10000);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        console.error('Batch polling failed:', err);
        dispatch(
          updateBatchProgress({ taskId: taskId!, status: 'failed', message: t('files.batch.failed').replace('{error}', errorMessage(err)) }),
        );
      }
    },
    [taskId, dispatch, t],
  );

  // Auto-resume polling for a batch job already running when the page mounts.
  useEffect(() => {
    if (activeBatch?.status === 'running' && activeBatch.jobId) {
      void startBatchPolling(activeBatch.jobId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  useEffect(() => {
    const checkServices = async () => {
      const [llm, graphiti] = await Promise.all([
        getLLMStatus().catch(() => ({ status: 'error' })),
        getGraphitiStatus().catch(() => ({ status: 'error', neo4j_connected: false })),
      ]);
      setLlmStatus(llm as LlmServiceStatus);
      setGraphitiStatus(graphiti as GraphitiStatus);
    };
    void checkServices();
  }, []);

  const loadFiles = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    setError(null);
    try {
      const [largest, ext] = await Promise.all([
        getLargestFiles(taskId, 200),
        getExtensionAnalysis(taskId),
      ]);
      const files = ((largest as { files?: FileRecord[] })?.files ?? []) as FileRecord[];
      setLargestFiles(files);
      setExtensionAnalysis(ext);

      // Index existing LLM descriptions by both full path and basename.
      const descMap: Record<string, LlmDescription> = {};
      files.forEach((file) => {
        const filePath = (file.path as string) || file.file_path;
        const f = file as Record<string, unknown>;
        if (f.llm_summary || f.llm_description || f.llm_keywords) {
          const desc: LlmDescription = {
            summary: f.llm_summary as string,
            description: f.llm_description as string,
            keywords:
              typeof f.llm_keywords === 'string'
                ? (f.llm_keywords as string).split(',').map((k) => k.trim())
                : ((f.llm_keywords as string[]) ?? []),
            model: f.llm_model_used as string,
            timestamp: f.llm_analyzed_at as string,
          };
          descMap[filePath] = desc;
          const base = filePath.split('/').pop();
          if (base && base !== filePath) descMap[base] = desc;
        }
      });
      if (Object.keys(descMap).length > 0) {
        setLlmResults((prev) => ({ ...descMap, ...prev }));
      }
    } catch (err) {
      const msg = errorMessage(err);
      setError(msg);
      toast.error(t('files.error.load_failed').replace('{error}', msg));
    } finally {
      setLoading(false);
    }
    // toast identity is stable enough; keeping it out avoids reload loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  const filteredFiles = useMemo(() => {
    return largestFiles.filter((f) => {
      const path = ((f.path as string) || f.file_path || '').toLowerCase();
      const size = Number(f.file_size ?? f.size ?? 0);
      if (filterExtension && !path.endsWith(filterExtension.toLowerCase())) return false;
      if (filterMinSize && size < Number(filterMinSize) * 1024 * 1024) return false;
      if (filterMaxSize && size > Number(filterMaxSize) * 1024 * 1024) return false;
      return true;
    });
  }, [largestFiles, filterExtension, filterMinSize, filterMaxSize]);

  const sortedFiles = useMemo(() => {
    const rows = [...filteredFiles];
    const dir = sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      switch (sortKey) {
        case 'name':
          return (
            dir *
            basename(getFilePath(a)).localeCompare(basename(getFilePath(b)), undefined, {
              numeric: true,
              sensitivity: 'base',
            })
          );
        case 'size':
          return dir * (getFileSize(a) - getFileSize(b));
        case 'mtime':
          return dir * (getFileMtimeMs(a) - getFileMtimeMs(b));
        default:
          return 0;
      }
    });
    return rows;
  }, [filteredFiles, sortKey, sortDir]);

  const handleSortChange = (key: FileSortKey) => {
    if (key === sortKey) {
      setSortParam(formatSortSpec(key, sortDir === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortParam(formatSortSpec(key, key === 'name' ? 'asc' : 'desc'));
    }
  };

  const clearFilters = () => {
    setFilterExtension('');
    setFilterMinSize('');
    setFilterMaxSize('');
  };

  const handleExportCsv = () => {
    if (!taskId) return;
    if (sortedFiles.length === 0) {
      toast.info(t('files.export.empty'));
      return;
    }
    const rows = sortedFiles.map((f) => {
      const p = getFilePath(f);
      const mtimeMs = getFileMtimeMs(f);
      return {
        name: basename(p),
        path: p,
        size_bytes: getFileSize(f),
        size_human: formatBytes(getFileSize(f)),
        extension: getFileExt(p),
        type: (f.file_type as string) ?? '',
        md5: (f.md5 as string) ?? '',
        sha256: (f.sha256 as string) ?? '',
        modified_time: mtimeMs ? formatDateTime(mtimeMs) : '',
        deleted: isDeletedFile(f) ? t('common.yes') : t('common.no'),
      };
    });
    downloadCSV(
      rows,
      `files-${taskId.slice(0, 8)}.csv`,
      [
        { key: 'name', label: t('files.csv.name') },
        { key: 'path', label: t('files.csv.path') },
        { key: 'size_bytes', label: t('files.csv.size_bytes') },
        { key: 'size_human', label: t('files.csv.size_human') },
        { key: 'extension', label: t('files.csv.extension') },
        { key: 'type', label: t('files.csv.type') },
        { key: 'md5', label: 'MD5' },
        { key: 'sha256', label: 'SHA-256' },
        { key: 'modified_time', label: t('files.csv.modified_time') },
        { key: 'deleted', label: t('files.csv.deleted') },
      ],
    );
    toast.success(t('files.export.success').replace('{n}', String(rows.length)));
  };

  const toggleFile = (path: string) =>
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const handleAnalyzeFile = async (file: FileRecord) => {
    if (!taskId) return;
    const filePath = ((file.path as string) || file.file_path)!;
    setLlmAnalyzingFiles((prev) => new Set(prev).add(filePath));
    try {
      const result = (await analyzeContent({
        taskId,
        content: undefined,
        filePath,
        filesDbPath: (currentTask as { output_files_db?: string })?.output_files_db ?? null,
      })) as { analysis?: LlmDescription };
      if (result?.analysis) {
        setLlmResults((prev) => ({
          ...prev,
          [filePath]: {
            summary: result.analysis!.summary,
            description: result.analysis!.description,
            keywords: result.analysis!.keywords ?? [],
          },
        }));
        dispatch(setRefreshFlag({ type: 'files' }));
        toast.success(t('files.toast.analyze_done'));
      }
    } catch (err) {
      toast.error(t('files.toast.analyze_failed').replace('{error}', errorMessage(err)));
    } finally {
      setLlmAnalyzingFiles((prev) => {
        const next = new Set(prev);
        next.delete(filePath);
        return next;
      });
    }
  };

  const handleAnalyzeDll = async (file: FileRecord) => {
    if (!taskId) return;
    const filePath = ((file.path as string) || file.file_path)!;
    setDllAnalyzingFiles((prev) => new Set(prev).add(filePath));
    try {
      await analyzeDLL({
        filePath,
        filesDbPath: (currentTask as { output_files_db?: string })?.output_files_db ?? null,
      });
      toast.success(t('files.toast.dll_done'));
      void loadFiles();
    } catch (err) {
      toast.error(t('files.toast.dll_failed').replace('{error}', errorMessage(err)));
    } finally {
      setDllAnalyzingFiles((prev) => {
        const next = new Set(prev);
        next.delete(filePath);
        return next;
      });
    }
  };

  const handleStartBatch = async () => {
    if (!taskId || selectedFiles.size === 0) return;
    try {
      const result = (await startBatchAnalysis(taskId, {
        filePaths: [...selectedFiles],
        modelType: 'text',
      })) as { job_id: string };
      dispatch(setBatchJob({ taskId, jobId: result.job_id }));
      toast.success(t('files.toast.batch_started').replace('{n}', String(selectedFiles.size)));
      void startBatchPolling(result.job_id);
    } catch (err) {
      toast.error(t('files.toast.batch_start_failed').replace('{error}', errorMessage(err)));
    }
  };

  const handleIngestGraphiti = async () => {
    if (!taskId) return;
    setGraphitiIngesting(true);
    try {
      await ingestTaskData(taskId);
      toast.success(t('files.toast.graphiti_started'));
    } catch (err) {
      toast.error(t('files.toast.graphiti_failed').replace('{error}', errorMessage(err)));
    } finally {
      setGraphitiIngesting(false);
    }
  };

  const handleReanalyze = async (hint: string) => {
    if (!taskId || selectedFiles.size === 0) return;
    setReanalyzing(true);
    try {
      await reanalyzeFiles(
        taskId,
        [...selectedFiles],
        hint,
        (currentTask as { output_files_db?: string })?.output_files_db ?? '',
        currentTask?.case_description ?? '',
      );
      toast.success(t('files.toast.reanalyze_started'));
      setShowReanalyzeModal(false);
    } catch (err) {
      toast.error(t('files.toast.reanalyze_failed').replace('{error}', errorMessage(err)));
    } finally {
      setReanalyzing(false);
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<FolderOpen size={36} />}
          title={t('files.empty.no_task.title')}
          description={t('files.empty.no_task.desc')}
        />
      </div>
    );
  }

  const detailPath = detailFile ? ((detailFile.path as string) || detailFile.file_path) ?? '' : '';
  const detailDesc = detailFile
    ? llmResults[detailPath] ?? llmResults[detailPath.split('/').pop() ?? '']
    : undefined;

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader icon={ FolderOpen } tone="emerald" title={t('nav.files')} subtitle={t('files.subtitle')} />
      <FilesHeader
        activeTab={activeTab}
        onTabChange={setTabParam}
        selectedCount={selectedFiles.size}
        isBatchRunning={Boolean(isBatchRunning)}
        batchMessage={activeBatch?.message}
        batchProgress={activeBatch?.progress}
        llmAvailable={llmStatus?.status === 'available' || llmStatus?.status === 'healthy'}
        graphitiConnected={Boolean(graphitiStatus?.neo4j_connected)}
        graphitiIngesting={graphitiIngesting}
        onStartBatch={handleStartBatch}
        onIngestGraphiti={handleIngestGraphiti}
        onOpenReanalyze={() => setShowReanalyzeModal(true)}
      />

      {activeTab === 'largest' && (
        <Card padded={false}>
          <LargestFilesTab
            files={sortedFiles}
            allFiles={largestFiles}
            loading={loading}
            error={error}
            density={density}
            sortKey={sortKey}
            sortDir={sortDir}
            selectedFiles={selectedFiles}
            llmResults={llmResults}
            llmAnalyzingFiles={llmAnalyzingFiles}
            dllAnalyzingFiles={dllAnalyzingFiles}
            filterExtension={filterExtension}
            filterMinSize={filterMinSize}
            filterMaxSize={filterMaxSize}
            onSortChange={handleSortChange}
            onDensityChange={setDensityParam}
            onFilterExtension={setFilterExtension}
            onFilterMinSize={setFilterMinSize}
            onFilterMaxSize={setFilterMaxSize}
            onClearFilters={clearFilters}
            onToggleFile={toggleFile}
            onAnalyzeFile={handleAnalyzeFile}
            onAnalyzeDll={handleAnalyzeDll}
            onOpenFile={setDetailFile}
            onRetry={() => void loadFiles()}
            onExportCsv={handleExportCsv}
          />
        </Card>
      )}

      {activeTab === 'extensions' && <ExtensionsTab data={extensionAnalysis} loading={loading} />}

      {activeTab === 'office' && taskId && <OfficePreviewTab taskId={taskId} />}

      {activeTab === 'extract' && taskId && <ExtractionPanel taskId={taskId} />}

      {showReanalyzeModal && (
        <ReanalyzeModal
          fileCount={selectedFiles.size}
          running={reanalyzing}
          onSubmit={handleReanalyze}
          onClose={() => setShowReanalyzeModal(false)}
        />
      )}

      <FileDetailDrawer
        file={detailFile}
        taskId={taskId}
        llmResult={detailDesc}
        llmAvailable={llmStatus?.status === 'available' || llmStatus?.status === 'healthy'}
        analyzing={detailPath !== '' && llmAnalyzingFiles.has(detailPath)}
        onAnalyze={handleAnalyzeFile}
        onClose={() => setDetailFile(null)}
      />
    </div>
  );
}
