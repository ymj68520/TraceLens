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
import FilesHeader from '../components/files/FilesHeader';
import LargestFilesTab from '../components/files/LargestFilesTab';
import ExtensionsTab from '../components/files/ExtensionsTab';
import ExtractionPanel from '../components/files/ExtractionPanel';
import OfficePreviewTab from '../components/files/OfficePreviewTab';
import ReanalyzeModal from '../components/files/ReanalyzeModal';
import { FolderOpen } from 'lucide-react';
import { errorMessage } from '../lib/utils';

export type FilesTab = 'largest' | 'extensions' | 'office' | 'extract';

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

  const { tasks } = useAppSelector((state) => state.tasks);
  const { activeBatchJobs } = useAppSelector((state) => state.intelligence);

  const activeBatch = taskId ? activeBatchJobs[taskId] : undefined;
  const isBatchRunning = activeBatch?.status === 'running';

  useEffect(() => {
    if (taskId && tasks.length === 0) {
      void dispatch(fetchTasks({}));
    }
  }, [taskId, tasks.length, dispatch]);

  const [largestFiles, setLargestFiles] = useState<FileRecord[]>([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<FilesTab>('largest');

  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [filterExtension, setFilterExtension] = useState('');
  const [filterMinSize, setFilterMinSize] = useState('');
  const [filterMaxSize, setFilterMaxSize] = useState('');

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
                message: (status.message as string) || `正在分析: ${processed}/${total}`,
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

        dispatch(updateBatchProgress({ taskId: taskId!, status: 'completed', message: '批量分析完成' }));
        setTimeout(() => dispatch(clearBatchJob({ taskId: taskId! })), 10000);
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        console.error('Batch polling failed:', err);
        dispatch(
          updateBatchProgress({ taskId: taskId!, status: 'failed', message: `失败: ${errorMessage(err)}` }),
        );
      }
    },
    [taskId, dispatch],
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
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
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
        toast.success('AI 分析完成');
      }
    } catch (err) {
      toast.error(`分析失败：${errorMessage(err)}`);
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
      toast.success('二进制分析完成');
      void loadFiles();
    } catch (err) {
      toast.error(`二进制分析失败：${errorMessage(err)}`);
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
      toast.success(`已启动批量分析（${selectedFiles.size} 个文件）`);
      void startBatchPolling(result.job_id);
    } catch (err) {
      toast.error(`启动失败：${errorMessage(err)}`);
    }
  };

  const handleIngestGraphiti = async () => {
    if (!taskId) return;
    setGraphitiIngesting(true);
    try {
      await ingestTaskData(taskId);
      toast.success('知识图谱导入已启动');
    } catch (err) {
      toast.error(`导入失败：${errorMessage(err)}`);
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
      toast.success('二次分析已启动');
      setShowReanalyzeModal(false);
    } catch (err) {
      toast.error(`二次分析失败：${errorMessage(err)}`);
    } finally {
      setReanalyzing(false);
    }
  };

  if (!taskId) {
    return (
      <div className="card">
        <EmptyState
          icon={<FolderOpen size={36} />}
          title="未选择任务"
          description="请从页面顶部的任务选择器中选择一个已完成的分析任务。"
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-7xl">
      <FilesHeader
        activeTab={activeTab}
        onTabChange={setActiveTab}
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
            files={filteredFiles}
            loading={loading}
            error={error}
            selectedFiles={selectedFiles}
            llmResults={llmResults}
            llmAnalyzingFiles={llmAnalyzingFiles}
            dllAnalyzingFiles={dllAnalyzingFiles}
            onToggleFile={toggleFile}
            onAnalyzeFile={handleAnalyzeFile}
            onAnalyzeDll={handleAnalyzeDll}
            filterExtension={filterExtension}
            filterMinSize={filterMinSize}
            filterMaxSize={filterMaxSize}
            onFilterExtension={setFilterExtension}
            onFilterMinSize={setFilterMinSize}
            onFilterMaxSize={setFilterMaxSize}
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
    </div>
  );
}
