import { useState, useCallback, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { 
  analyzeContent, 
  startBatchAnalysis, 
  pollBatchStatus, 
  getLLMStatus 
} from '../services/llmService';
import { 
  setBatchJob, 
  updateBatchProgress, 
  clearBatchJob, 
  setRefreshFlag 
} from '../store/intelligenceSlice';

/**
 * Custom hook for LLM file analysis
 */
export const useFileLLMAnalysis = (taskId) => {
  const dispatch = useDispatch();
  const { activeBatchJobs } = useSelector((state) => state.intelligence);
  
  const [llmStatus, setLlmStatus] = useState(null);
  const [llmAnalyzingFiles, setLlmAnalyzingFiles] = useState(new Set());
  const [llmResults, setLlmResults] = useState({});
  const [existingLlmDescriptions, setExistingLlmDescriptions] = useState({});
  const [expandedDescriptions, setExpandedDescriptions] = useState(new Set());

  const activeBatch = activeBatchJobs[taskId];
  const isBatchRunning = activeBatch && activeBatch.status === "running";

  // Auto-resume batch analysis polling
  useEffect(() => {
    if (activeBatch && activeBatch.status === 'running' && activeBatch.jobId) {
      console.log(`[useFileLLMAnalysis] Auto-resuming batch analysis: ${activeBatch.jobId}`);
      startBatchAnalysisPolling(activeBatch.jobId);
    }
  }, [taskId]);

  const startBatchAnalysisPolling = useCallback(async (jobId) => {
    try {
      const finalStatus = await pollBatchStatus(jobId, (status) => {
        const processed = status.files_processed || 0;
        const total = status.files_total || 1;
        dispatch(updateBatchProgress({
          taskId,
          progress: Math.round((processed / total) * 100),
          message: status.message || `正在分析: ${processed}/${total}`
        }));
      }, 2000);

      if (finalStatus.results) {
        const newDesc = {};
        finalStatus.results.forEach((r) => {
          if (r.file_path && r.analysis) {
            newDesc[r.file_path] = {
              summary: r.analysis.summary || r.analysis.description?.substring(0, 200),
              description: r.analysis.description,
              keywords: r.analysis.keywords || [],
            };
          }
        });
        setLlmResults(prev => ({ ...prev, ...newDesc }));
        dispatch(setRefreshFlag({ type: 'files' }));
      }

      dispatch(updateBatchProgress({ taskId, status: 'completed', message: '✅ 批量分析完成' }));
      setTimeout(() => dispatch(clearBatchJob({ taskId })), 10000);
    } catch (err) {
      console.error('Batch analysis polling error:', err);
      dispatch(updateBatchProgress({ taskId, status: 'failed', message: `❌ ${err.message}` }));
      setTimeout(() => dispatch(clearBatchJob({ taskId })), 10000);
    }
  }, [taskId, dispatch]);

  const handleBatchAnalyze = useCallback(async (selectedFilePaths) => {
    if (!taskId || selectedFilePaths.length === 0) return;

    try {
      const result = await startBatchAnalysis({
        task_id: taskId,
        file_paths: selectedFilePaths
      });

      const jobId = result.job_id;
      dispatch(setBatchJob({
        taskId,
        jobId,
        status: 'running',
        progress: 0,
        message: '批量分析已启动...'
      }));

      await startBatchAnalysisPolling(jobId);
    } catch (err) {
      console.error('Failed to start batch analysis:', err);
      alert(`批量分析失败: ${err.message}`);
    }
  }, [taskId, dispatch, startBatchAnalysisPolling]);

  const handleSingleAnalyze = useCallback(async (filePath) => {
    if (!taskId) return;

    setLlmAnalyzingFiles(prev => new Set(prev).add(filePath));

    try {
      const result = await analyzeContent({
        task_id: taskId,
        file_path: filePath
      });

      if (result.analysis) {
        setLlmResults(prev => ({
          ...prev,
          [filePath]: {
            summary: result.analysis.summary || result.analysis.description?.substring(0, 200),
            description: result.analysis.description,
            keywords: result.analysis.keywords || []
          }
        }));
      }
    } catch (err) {
      console.error(`Failed to analyze ${filePath}:`, err);
      alert(`分析失败: ${err.message}`);
    } finally {
      setLlmAnalyzingFiles(prev => {
        const newSet = new Set(prev);
        newSet.delete(filePath);
        return newSet;
      });
    }
  }, [taskId]);

  const toggleDescriptionExpansion = useCallback((filePath) => {
    setExpandedDescriptions(prev => {
      const newSet = new Set(prev);
      if (newSet.has(filePath)) {
        newSet.delete(filePath);
      } else {
        newSet.add(filePath);
      }
      return newSet;
    });
  }, []);

  const fetchLLMStatus = useCallback(async () => {
    if (!taskId) return;
    
    try {
      const status = await getLLMStatus(taskId);
      setLlmStatus(status);
      
      if (status.descriptions) {
        const descriptions = {};
        status.descriptions.forEach(desc => {
          descriptions[desc.file_path] = {
            summary: desc.summary,
            description: desc.description,
            keywords: desc.keywords || []
          };
        });
        setExistingLlmDescriptions(descriptions);
      }
    } catch (err) {
      console.error('Failed to fetch LLM status:', err);
    }
  }, [taskId]);

  useEffect(() => {
    fetchLLMStatus();
  }, [fetchLLMStatus]);

  return {
    llmStatus,
    llmAnalyzingFiles,
    llmResults,
    existingLlmDescriptions,
    expandedDescriptions,
    isBatchRunning,
    activeBatch,
    handleBatchAnalyze,
    handleSingleAnalyze,
    toggleDescriptionExpansion,
    fetchLLMStatus
  };
};
