import { motion } from 'framer-motion';
import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { fetchTasks } from '../store/taskSlice';
import { setBatchJob, updateBatchProgress, clearBatchJob, setRefreshFlag } from '../store/intelligenceSlice';
import Card from '../components/common/Card';
import Spinner from '../components/common/Spinner';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';
import { startExtraction, pollExtractionStatus } from '../services/extractionService';
import { analyzeContent, analyzeDLL, startBatchAnalysis, pollBatchStatus, getLLMStatus } from '../services/llmService';
import { reanalyzeFiles, getCaseAnalysisStatus } from '../services/caseAnalysisService';
import { ingestTaskData, getGraphitiStatus } from '../services/graphitiService';
// Subcomponents (JSX split out for maintainability; behavior unchanged)
import FilesHeader from '../components/files/FilesHeader';
import FileFilters from '../components/files/FileFilters';
import ExtractionControls from '../components/files/ExtractionControls';
import FileListTable from '../components/files/FileListTable';
import ExtensionAnalysisTab from '../components/files/ExtensionAnalysisTab';
import OfficePreviewTab from '../components/files/OfficePreviewTab';
import ReanalyzeModal from '../components/files/ReanalyzeModal';

const Files = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const dispatch = useDispatch();

  // 1. Hooks - State from Redux
  const { tasks } = useSelector((state) => state.tasks);
  const { activeBatchJobs } = useSelector((state) => state.intelligence);

  // 2. Derived State - MUST happen after hooks
  const activeBatch = activeBatchJobs[taskId];
  const isBatchRunning = activeBatch && activeBatch.status === "running";

  // 3. Initial effects
  useEffect(() => {
    if (taskId && tasks.length === 0) {
      dispatch(fetchTasks());
    }
  }, [taskId, tasks.length, dispatch]);

  const [largestFiles, setLargestFiles] = useState([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('largest');

  // File selection state
  const [selectedFiles, setSelectedFiles] = useState(new Set());
  const [selectAll, setSelectAll] = useState(false);

  // Filter state
  const [filterExtension, setFilterExtension] = useState('');
  const [filterMinSize, setFilterMinSize] = useState('');
  const [filterMaxSize, setFilterMaxSize] = useState('');

  // LLM Analysis state
  const [llmStatus, setLlmStatus] = useState(null);
  const [llmAnalyzingFiles, setLlmAnalyzingFiles] = useState(() => new Set());
  const [dllAnalyzingFiles, setDllAnalyzingFiles] = useState(() => new Set());
  const [llmResults, setLlmResults] = useState({});
  const [existingLlmDescriptions, setExistingLlmDescriptions] = useState({});
  const [expandedDescriptions, setExpandedDescriptions] = useState(new Set());

  // AUTO-RESUME: Detect active batch job on mount
  useEffect(() => {
    if (activeBatch && activeBatch.status === 'running' && activeBatch.jobId) {
      console.log(`[Files] Auto-resuming batch analysis polling: ${activeBatch.jobId}`);
      startBatchAnalysisPolling(activeBatch.jobId);
    }
  }, [taskId]); // Re-run if taskId changes

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

      // Success processing
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

        // Set refresh flag to notify CaseIntelligence to refresh
        dispatch(setRefreshFlag({ type: 'files' }));
      }

      dispatch(updateBatchProgress({ taskId, status: 'completed', message: '✅ 批量分析完成' }));
      setTimeout(() => dispatch(clearBatchJob({ taskId })), 10000);
    } catch (err) {
      console.error('Batch polling failed:', err);
      dispatch(updateBatchProgress({ taskId, status: 'failed', message: '❌ 失败: ' + err.message }));
    }
  }, [taskId, dispatch]);

  // Graphiti state
  const [graphitiStatus, setGraphitiStatus] = useState(null);
  const [graphitiIngesting, setGraphitiIngesting] = useState(false);
  const [graphitiMessage, setGraphitiMessage] = useState('');

  // Extraction state
  const [extractionMode, setExtractionMode] = useState('all');
  const [extractionPattern, setExtractionPattern] = useState('');
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [extractionStatus, setExtractionStatus] = useState('idle');
  const [extractionProgress, setExtractionProgress] = useState(0);
  const [extractionMessage, setExtractionMessage] = useState('');
  const [extractedCount, setExtractedCount] = useState(0);
  const [skippedCount, setSkippedCount] = useState(0);
  const [extractionError, setExtractionError] = useState(null);

  // Office preview state
  const [officePreview, setOfficePreview] = useState(null);
  const [officeParsing, setOfficeParsing] = useState(false);
  const [officeError, setOfficeError] = useState(null);

  // Re-analysis state
  const [showReanalyzeModal, setShowReanalyzeModal] = useState(false);
  const [reanalyzeHint, setReanalyzeHint] = useState('');
  const [reanalyzeTargetFiles, setReanalyzeTargetFiles] = useState([]);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeMessage, setReanalyzeMessage] = useState('');

  const currentTask = tasks.find((t) => t.id === taskId);

  // Check LLM and Graphiti service status
  useEffect(() => {
    const checkServices = async () => {
      try {
        const [llm, graphiti] = await Promise.all([
          getLLMStatus().catch(() => ({ status: 'error' })),
          getGraphitiStatus().catch(() => ({ status: 'error', neo4j_connected: false })),
        ]);
        setLlmStatus(llm);
        setGraphitiStatus(graphiti);
      } catch (err) {
        console.error('Failed to check service status:', err);
      }
    };
    checkServices();
  }, []);

  // Load existing LLM descriptions from largestFiles data
  useEffect(() => {
    if (!taskId || largestFiles.length === 0) return;

    const extractDescriptions = () => {
      const descMap = {};
      largestFiles.forEach((file) => {
        const filePath = file.path || file.file_path;

        // Check if file has LLM fields (from database)
        if (file.llm_summary || file.llm_description || file.llm_keywords) {
          const descData = {
            summary: file.llm_summary,
            description: file.llm_description,
            keywords: file.llm_keywords ? (
              typeof file.llm_keywords === 'string'
                ? file.llm_keywords.split(',').map(k => k.trim())
                : file.llm_keywords
            ) : [],
            model: file.llm_model_used,
            timestamp: file.llm_analyzed_at
          };

          // Store with multiple keys for robust lookup
          descMap[filePath] = descData;

          // Also store with basename
          const basename = filePath.split('/').pop();
          if (basename && basename !== filePath) {
            descMap[basename] = descData;
          }
        }
      });

      if (Object.keys(descMap).length > 0) {
        setExistingLlmDescriptions(prev => ({ ...prev, ...descMap }));
      }
    };

    extractDescriptions();
  }, [taskId, largestFiles]);

  // Apply filters to files
  const getFilteredFiles = useCallback(() => {
    let filtered = [...largestFiles];

    if (filterExtension) {
      const exts = filterExtension.toLowerCase().split(',').map(e => e.trim());
      filtered = filtered.filter(f => {
        const ext = (f.extension || '').toLowerCase();
        return exts.some(e => ext.includes(e) || ext === e);
      });
    }

    if (filterMinSize) {
      const minBytes = parseFloat(filterMinSize) * 1024; // KB
      filtered = filtered.filter(f => (f.size || f.file_size || 0) >= minBytes);
    }

    if (filterMaxSize) {
      const maxBytes = parseFloat(filterMaxSize) * 1024; // KB
      filtered = filtered.filter(f => (f.size || f.file_size || 0) <= maxBytes);
    }

    return filtered;
  }, [largestFiles, filterExtension, filterMinSize, filterMaxSize]);

  const filteredFiles = getFilteredFiles();

  // Handle select all
  const handleSelectAll = (checked) => {
    setSelectAll(checked);
    if (checked) {
      setSelectedFiles(new Set(filteredFiles.map((f, idx) => idx)));
    } else {
      setSelectedFiles(new Set());
    }
  };

  // Handle single file selection
  const handleFileSelect = (index) => {
    const newSelected = new Set(selectedFiles);
    if (newSelected.has(index)) {
      newSelected.delete(index);
    } else {
      newSelected.add(index);
    }
    setSelectedFiles(newSelected);
    setSelectAll(newSelected.size === filteredFiles.length);
  };

  // DLL file analysis via Python service
  const analyzeDLLFile = async ({ filePath, filesDbPath }) => {
    return await analyzeDLL({
      filePath,
      filesDbPath,
    });
  };

  // Analyze single file
  const handleAnalyzeSingleFile = async (file, index) => {
    let filePath = file.path || file.file_path || file.name;
    if (!filePath) {
      alert('无法获取文件路径，分析失败');
      return;
    }

    // If path is not absolute, assume it's relative to extraction directory
    const isAbsolutePath = filePath.startsWith('/') || filePath.includes(':');
    if (!isAbsolutePath && currentTask?.extraction_directory) {
      filePath = `${currentTask.extraction_directory}/${filePath}`;
    }
    // Fallback to default extraction directory
    else if (!isAbsolutePath) {
      filePath = `../build/data/tasks/${taskId}/extracted_files/${filePath}`;
    }

    // Check file extension and size
    const extension = (file.extension || filePath.split('.').pop()).toLowerCase();
    const fileSize = file.size || file.file_size || 0;

    // Detect DLL/EXE/SYS files (binary executables)
    const dllExtensions = ['dll', 'exe', 'sys', 'ocx', 'cpl', 'so', 'dylib'];
    const isDLL = dllExtensions.includes(extension);

    // Determine model type based on file extension
    const imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'tif'];
    const isImage = imageExtensions.includes(extension);
    const modelType = isImage ? 'vision' : 'text';

    setLlmAnalyzingFiles(prev => new Set(prev).add(index));

    try {
      let result;

      // DLL/EXE/SYS file analysis
      if (isDLL) {
        setDllAnalyzingFiles(prev => new Set(prev).add(index));
        console.log('Analyzing DLL file:', filePath, `(${extension}, ${(fileSize / 1024).toFixed(1)} KB)`);

        try {
          result = await analyzeDLLFile({
            filePath: filePath,
            filesDbPath: currentTask?.output_files_db || null
          });

          console.log('DLL analysis result:', result);

          if (result.success && result.analysis) {
            const analysis = result.analysis;
            const descData = {
              summary: analysis.function_assessment || analysis.description?.substring(0, 200),
              description: analysis.description || analysis.function_assessment,
              keywords: analysis.iocs || [],
              model: result.model_used,
              timestamp: result.timestamp,
              isDLLAnalysis: true,
              threatLevel: analysis.threat_level,
              confidence: analysis.confidence,
              suspiciousBehaviors: analysis.suspicious_behaviors || [],
              mitreTechniques: analysis.mitre_attack_techniques || [],
              recommendations: analysis.recommendations
            };

            console.log('Setting DLL analysis result for', filePath, ':', descData);

            setLlmResults(prev => ({
              ...prev,
              [filePath]: descData
            }));

            // Also update the file in largestFiles to reflect the change
            setLargestFiles(prev => prev.map((f, i) =>
              i === index ? {
                ...f,
                llm_summary: descData.summary,
                llm_description: descData.description,
                llm_keywords: descData.keywords,
                threat_level: descData.threatLevel,
                is_dll_analysis: true
              } : f
            ));

            // Set refresh flag to notify CaseIntelligence to refresh
            dispatch(setRefreshFlag({ type: 'files' }));
          } else {
            console.error('DLL analysis failed: no success in response');
            alert('DLL分析失败：未收到有效响应');
          }
        } catch (dllErr) {
          console.error('DLL analysis failed:', dllErr);

          // Provide specific error messages for DLL analysis
          let errorMsg = dllErr.response?.data?.detail || dllErr.message || '未知错误';

          if (!dllErr.response && dllErr.code === 'ERR_NETWORK') {
            errorMsg = `DLL分析服务未运行\n\n提示：\n1. 请确保 C++ 服务已启动: ./build/forensic_analyzer --http-server 8666\n2. 请确保 Python 服务已启动: python -m python_service.httpserver.main\n3. 或使用启动脚本: ./run.sh`;
          } else if (dllErr.response?.status === 400 || dllErr.response?.status === 404) {
            const detail = dllErr.response?.data?.detail || '';
            if (detail.includes('File not found') || detail.includes('not found')) {
              errorMsg = `❌ DLL文件未找到\n\n${detail}\n\n建议：使用"批量提取"功能先提取文件`;
            }
          }

          alert(`DLL分析失败: ${errorMsg}\n\n文件: ${file.name || filePath}\n类型: ${extension.toUpperCase()}\n大小: ${(fileSize / 1024).toFixed(1)} KB`);
        } finally {
          setDllAnalyzingFiles(prev => {
            const next = new Set(prev);
            next.delete(index);
            return next;
          });
        }
      } else {
        // Existing non-DLL file analysis logic
        console.log('Analyzing file:', filePath, `(${extension}, ${(fileSize / 1024).toFixed(1)} KB, model: ${modelType})`);

        const result = await analyzeContent({
          filePath: filePath,
          dbFilePath: file.path || file.file_path,
          modelType: modelType,
          filesDbPath: currentTask?.output_files_db || null,
        });

        console.log('Analysis result:', result);

        if (result.success && result.analysis) {
          const analysis = result.analysis;
          const descData = {
            summary: analysis.summary || analysis.description?.substring(0, 200),
            description: analysis.description,
            keywords: analysis.keywords || [],
            model: result.model_used,
            timestamp: result.timestamp || new Date().toISOString()
          };

          console.log('Setting LLM result for', filePath, ':', descData);

          setLlmResults(prev => ({
            ...prev,
            [filePath]: descData
          }));

          // Also update the file in largestFiles to reflect the change
          setLargestFiles(prev => prev.map((f, i) =>
            i === index ? { ...f, llm_summary: descData.summary, llm_description: descData.description, llm_keywords: descData.keywords } : f
          ));

          // Set refresh flag to notify CaseIntelligence to refresh
          dispatch(setRefreshFlag({ type: 'files' }));
        } else {
          console.error('Analysis failed: no success in response');
          alert('分析失败：未收到有效响应');
        }
      }
    } catch (err) {
      console.error('Failed to analyze file:', err);

      // Better error messages
      let errorMsg = err.response?.data?.detail || err.message || '未知错误';

      // Check for Python service not available
      if (!err.response && err.code === 'ERR_NETWORK') {
        errorMsg = `Python LLM 服务未运行\n\n提示：\n1. 请启动 Python 服务：python -m python_service.httpserver.main\n2. 或使用启动脚本：./scripts/start_services.sh`;
      }
      // Check for file not found error
      else if (err.response?.status === 400 || err.response?.status === 404) {
        const detail = err.response?.data?.detail || err.message || '';
        if (detail.includes('No such file or directory') || detail.includes('[Errno 2]') || detail.includes('not found')) {
          errorMsg = `❌ 文件未找到

${detail}

建议操作：
1. 使用"批量提取"功能先提取所有文件
2. 或使用案情分析功能（会自动提取和分析文件）

当前路径：${filePath}`;
        } else if (err.response?.status === 400) {
          errorMsg = '文件内容不兼容（可能是二进制文件或编码问题）';
        } else if (err.response?.status === 404) {
          errorMsg = 'LLM API 端点未找到，请检查 Python 服务是否正常运行';
        }
      } else if (err.response?.status === 500) {
        errorMsg = '服务器处理失败（文件可能过大或格式不支持）';
      }

      alert(`分析失败: ${errorMsg}\n\n文件: ${file.name || filePath}\n类型: ${extension.toUpperCase()}\n大小: ${(fileSize / 1024).toFixed(1)} KB`);
    } finally {
      setLlmAnalyzingFiles(prev => {
        const next = new Set(prev);
        next.delete(index);
        return next;
      });
    }
  };

  // Batch analyze selected files or all files if none selected
  const handleBatchAnalyze = async () => {
    let filesToAnalyze = [];

    if (selectedFiles.size === 0) {
      // No files selected - analyze all filtered files
      filesToAnalyze = filteredFiles.map(f => f.path || f.file_path).filter(Boolean);

      if (filesToAnalyze.length === 0) {
        alert('当前筛选结果中没有可分析的文件');
        return;
      }

      if (!confirm(`将分析当前筛选结果中的所有 ${filesToAnalyze.length} 个文件，是否继续？`)) {
        return;
      }
    } else {
      // Files selected - analyze only selected files
      filesToAnalyze = [...selectedFiles]
        .map(idx => filteredFiles[idx])
        .filter(Boolean)
        .map(f => f.path || f.file_path)
        .filter(Boolean);

      if (filesToAnalyze.length === 0) {
        alert('选中的文件无效或路径缺失');
        return;
      }
    }

    try {
      const result = await startBatchAnalysis(taskId, {
        filePaths: filesToAnalyze,
        modelType: 'text',
      });

      if (result.job_id) {
        dispatch(setBatchJob({ taskId, jobId: result.job_id }));
        startBatchAnalysisPolling(result.job_id);
      }
    } catch (err) {
      console.error('Batch analysis failed:', err);
      const errorMsg = err.response?.data?.detail || err.message || '未知错误';
      alert(`批量分析启动失败: ${errorMsg}`);
    }
  };

  // Ingest to Graphiti
  const handleGraphitiIngest = async () => {
    if (!taskId) return;

    setGraphitiIngesting(true);
    setGraphitiMessage('正在导入知识图谱...');

    try {
      const result = await ingestTaskData(taskId, {
        includeLLMDescriptions: true,
      });
      setGraphitiMessage(result.message || '导入成功');
    } catch (err) {
      console.error('Graphiti ingestion failed:', err);
      setGraphitiMessage('导入失败: ' + (err.message || '未知错误'));
    } finally {
      setGraphitiIngesting(false);
    }
  };

  // Open re-analysis modal for single or multiple files
  const openReanalyzeModal = (filePaths) => {
    // Convert relative paths to absolute paths
    const absolutePaths = filePaths.map(toAbsolutePath);

    console.log('Opening reanalyze modal with paths:', absolutePaths);
    setReanalyzeTargetFiles(absolutePaths);
    setReanalyzeHint('');
    setReanalyzeMessage('');
    setShowReanalyzeModal(true);
  };

  // Handle re-analysis submission
  const handleReanalyze = async () => {
    if (!reanalyzeHint.trim() || reanalyzeTargetFiles.length === 0) return;

    setReanalyzing(true);
    setReanalyzeMessage(`正在重新分析 ${reanalyzeTargetFiles.length} 个文件...`);

    try {
      const filesDbPath = currentTask?.output_files_db || currentTask?.output_files_db_path || '';
      console.log('Starting reanalyze with:', {
        taskId,
        fileCount: reanalyzeTargetFiles.length,
        filesDbPath,
        hint: reanalyzeHint.trim(),
      });

      const result = await reanalyzeFiles(
        taskId,
        reanalyzeTargetFiles,
        reanalyzeHint.trim(),
        filesDbPath,
      );

      console.log('Reanalyze started:', result);

      if (result.job_id) {
        // Poll for completion
        const poll = async () => {
          try {
            const status = await getCaseAnalysisStatus(result.job_id);
            console.log('Reanalyze status:', status);

            if (status.status === 'completed') {
              setReanalyzeMessage(`✅ 重新分析完成`);
              // Refresh file list - update both llmResults and existingLlmDescriptions
              if (status.result?.results) {
                const newDesc = {};
                status.result.results.forEach((r) => {
                  if (r.file_path && r.success) {
                    console.log(`Updating description for ${r.file_path}`);

                    const descData = {
                      summary: r.description?.substring(0, 200),
                      description: r.description,
                      keywords: [],
                      model: r.model_used,
                      timestamp: new Date().toISOString(),
                    };

                    // Store with multiple keys for robust lookup
                    // 1. Full path (as returned from backend)
                    newDesc[r.file_path] = descData;

                    // 2. Basename only (for matching with file.path)
                    const basename = r.file_path.split('/').pop();
                    if (basename && basename !== r.file_path) {
                      newDesc[basename] = descData;
                    }
                  } else if (r.file_path && r.error) {
                    console.error(`Failed to analyze ${r.file_path}:`, r.error);
                  }
                });

                console.log('New descriptions to add:', Object.keys(newDesc));

                // Update both states to ensure new descriptions are displayed
                setLlmResults(prev => ({ ...prev, ...newDesc }));
                setExistingLlmDescriptions(prev => ({ ...prev, ...newDesc }));

                // Also refresh the file data from backend to get latest database values
                try {
                  const refreshedData = await getLargestFiles(taskId, 100);
                  setLargestFiles(refreshedData.largest_files || refreshedData.files || refreshedData || []);
                } catch (err) {
                  console.error('Failed to refresh file data:', err);
                }

                // Set refresh flag to notify CaseIntelligence to refresh
                dispatch(setRefreshFlag({ type: 'files' }));
              }
              setReanalyzing(false);
              setTimeout(() => setShowReanalyzeModal(false), 1500);
            } else if (status.status === 'failed') {
              setReanalyzeMessage(`❌ 分析失败: ${status.detail}`);
              setReanalyzing(false);
            } else {
              setReanalyzeMessage(status.detail || '分析中...');
              setTimeout(poll, 2000);
            }
          } catch (err) {
            setReanalyzeMessage(`❌ 状态查询失败: ${err.message}`);
            setReanalyzing(false);
          }
        };
        poll();
      }
    } catch (err) {
      setReanalyzeMessage(`❌ 启动失败: ${err.message || '未知错误'}`);
      setReanalyzing(false);
    }
  };

  // Toggle LLM description expansion
  const toggleDescription = (filePath) => {
    const newExpanded = new Set(expandedDescriptions);
    if (newExpanded.has(filePath)) {
      newExpanded.delete(filePath);
    } else {
      newExpanded.add(filePath);
    }
    setExpandedDescriptions(newExpanded);
  };

  // Convert relative file path to absolute path
  const toAbsolutePath = (filePath) => {
    if (!filePath) return filePath;

    // If path is already absolute, return as is
    const isAbsolutePath = filePath.startsWith('/') || filePath.includes(':');
    if (isAbsolutePath) return filePath;

    // Try to use extraction directory from task
    if (currentTask?.extraction_directory) {
      return `${currentTask.extraction_directory}/${filePath}`;
    }

    // Fallback to default extraction directory
    return `../build/data/tasks/${taskId}/extracted_files/${filePath}`;
  };

  // Get LLM description for a file
  const getLLMDescription = (file) => {
    const filePath = file.path || file.file_path;

    // First check if file object has LLM fields directly (from database)
    if (file.llm_summary || file.llm_description || file.llm_keywords) {
      return {
        summary: file.llm_summary,
        description: file.llm_description,
        keywords: file.llm_keywords,
        model: file.llm_model_used,
        timestamp: file.llm_analyzed_at,
        threatLevel: file.threat_level,
        isDLLAnalysis: file.is_dll_analysis
      };
    }

    // Then check from session results and pre-loaded descriptions
    // Try multiple key formats: full path, basename, etc.
    const basename = filePath.split('/').pop() || filePath;

    // Check with full path
    if (llmResults[filePath]) {
      return llmResults[filePath];
    }
    if (existingLlmDescriptions[filePath]) {
      return existingLlmDescriptions[filePath];
    }

    // Check with basename
    if (llmResults[basename]) {
      return llmResults[basename];
    }
    if (existingLlmDescriptions[basename]) {
      return existingLlmDescriptions[basename];
    }

    // Check with absolute path
    const absolutePath = toAbsolutePath(filePath);
    if (llmResults[absolutePath]) {
      return llmResults[absolutePath];
    }
    if (existingLlmDescriptions[absolutePath]) {
      return existingLlmDescriptions[absolutePath];
    }

    return null;
  };

  // Handle extraction start
  const handleStartExtraction = async () => {
    if (!taskId) return;

    setExtractionStatus('pending');
    setExtractionProgress(0);
    setExtractionMessage('Starting extraction...');
    setExtractionError(null);
    setExtractedCount(0);
    setSkippedCount(0);

    try {
      const result = await startExtraction(taskId, {
        mode: extractionMode,
        pattern: extractionPattern,
        includeDeleted: includeDeleted,
        overwrite: overwrite,
      });

      if (!result.job_id) {
        throw new Error('No job ID returned');
      }

      setExtractionStatus('running');
      setExtractionMessage('Extraction in progress...');

      const finalStatus = await pollExtractionStatus(
        result.job_id,
        (status) => {
          setExtractionProgress(status.progress || 0);
          setExtractionMessage(status.message || 'Extracting...');
          setExtractedCount(status.extracted_files || 0);
          setSkippedCount(status.skipped_files || 0);
        },
        1000
      );

      setExtractionStatus('completed');
      setExtractionMessage(`Results: ${finalStatus.extracted_files} extracted, ${finalStatus.skipped_files || 0} skipped`);
      setExtractedCount(finalStatus.extracted_files || 0);
      setSkippedCount(finalStatus.skipped_files || 0);

    } catch (err) {
      console.error('Extraction failed:', err);
      setExtractionStatus('failed');
      setExtractionError(err.message || 'Extraction failed');
      setExtractionMessage('Extraction failed');
    }
  };

  useEffect(() => {
    if (!taskId) {
      setError('No task ID provided. Please select a task from the Tasks page.');
      return;
    }

    const fetchData = async () => {
      setLoading(true);
      setError(null);

      try {
        let largestData = [];
        let extensionData = null;

        try {
          largestData = await getLargestFiles(taskId, 100);
        } catch (err) {
          console.error('Failed to fetch largest files:', err);
          largestData = [];
        }

        try {
          extensionData = await getExtensionAnalysis(taskId);
        } catch (err) {
          console.error('Failed to fetch extension analysis:', err);
          extensionData = null;
        }

        setLargestFiles(largestData.largest_files || largestData.files || largestData || []);
        setExtensionAnalysis(extensionData);
      } catch (err) {
        console.error('Failed to fetch file data:', err);
        setError(err.message || 'Failed to load file data');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [taskId]);


  if (!taskId) {
    return (
      <div className="space-y-6">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">文件分析</motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">分析和浏览分类后的文件</p>
        </div>

        <Card title="选择任务">
          <p className="text-slate-500 dark:text-slate-400">
            请从{' '}
            <a href="/tasks" className="text-primary-600 hover:text-blue-800 dark:text-primary-400 dark:hover:text-blue-300">
              任务页面
            </a>{' '}
            选择一个已完成的任务，或使用顶部的任务选择器。
          </p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">文件分析</motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-slate-600 dark:text-slate-300">加载文件数据...</span>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">文件分析</motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
        </div>

        <Card title="错误">
          <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
            <p className="text-red-800 dark:text-red-200">{error}</p>
          </div>
        </Card>
      </div>
    );
  }


  return (
    <div className="space-y-6">
      <FilesHeader
        currentTask={currentTask}
        taskId={taskId}
        llmStatus={llmStatus}
        graphitiStatus={graphitiStatus}
      />

      {/* Unified Forensic Control Console */}
      <Card className="border-t-4 border-t-purple-500 shadow-lg">
        <div className="space-y-6">
          {/* Header Status & Selection Info */}
          <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-100 dark:border-slate-700">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                <span className="text-slate-500 dark:text-slate-400 font-medium">服务状态:</span>
                <span className={`flex items-center gap-1.5 ${(llmStatus?.status === 'healthy' || llmStatus?.status === 'available') ? 'text-green-600' : 'text-red-600'}`}>
                  <span className={`w-2 h-2 rounded-full ${(llmStatus?.status === 'healthy' || llmStatus?.status === 'available') ? 'bg-green-500' : 'bg-red-500'}`} />
                  AI
                </span>
                <span className={`flex items-center gap-1.5 ${graphitiStatus?.neo4j_connected ? 'text-green-600' : 'text-red-600'}`}>
                  <span className={`w-2 h-2 rounded-full ${graphitiStatus?.neo4j_connected ? 'bg-green-500' : 'bg-red-500'}`} />
                  KG
                </span>
              </div>
              <div className="text-slate-600 dark:text-slate-300">
                已选: <span className="font-bold text-purple-600">{selectedFiles.size}</span>
                {Object.keys(existingLlmDescriptions).length > 0 && (
                  <span className="ml-3 opacity-75">
                    (含描述: <span className="text-green-600">{Object.keys(existingLlmDescriptions).length}</span>)
                  </span>
                )}
              </div>
            </div>

            <div className="flex gap-2 text-xs text-slate-500 dark:text-slate-400">
              <span>显示 {filteredFiles.length} / {largestFiles.length} 个文件</span>
            </div>
          </div>

          {/* Configuration Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <FileFilters
              filterExtension={filterExtension}
              setFilterExtension={setFilterExtension}
              filterMinSize={filterMinSize}
              setFilterMinSize={setFilterMinSize}
              filterMaxSize={filterMaxSize}
              setFilterMaxSize={setFilterMaxSize}
            />
            <ExtractionControls
              extractionMode={extractionMode}
              setExtractionMode={setExtractionMode}
              extractionPattern={extractionPattern}
              setExtractionPattern={setExtractionPattern}
              includeDeleted={includeDeleted}
              setIncludeDeleted={setIncludeDeleted}
              overwrite={overwrite}
              setOverwrite={setOverwrite}
              extractionStatus={extractionStatus}
              extractionProgress={extractionProgress}
              extractionMessage={extractionMessage}
              handleStartExtraction={handleStartExtraction}
              llmStatus={llmStatus}
              isBatchRunning={isBatchRunning}
              activeBatch={activeBatch}
              graphitiStatus={graphitiStatus}
              graphitiIngesting={graphitiIngesting}
              graphitiMessage={graphitiMessage}
              handleBatchAnalyze={handleBatchAnalyze}
              handleGraphitiIngest={handleGraphitiIngest}
              openReanalyzeModal={openReanalyzeModal}
              selectedFiles={selectedFiles}
              filteredFiles={filteredFiles}
            />
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="border-b border-slate-200 dark:border-slate-700">
        <nav className="-mb-px flex space-x-8">
          {[
            { id: 'largest', label: '文件列表' },
            { id: 'extensions', label: '扩展名分析' },
            { id: 'office', label: '📄 Office 预览' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`${activeTab === tab.id
                ? 'border-blue-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400'
                } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* File List Tab */}
      {activeTab === 'largest' && (
        <FileListTable
          filteredFiles={filteredFiles}
          selectAll={selectAll}
          handleSelectAll={handleSelectAll}
          selectedFiles={selectedFiles}
          handleFileSelect={handleFileSelect}
          llmAnalyzingFiles={llmAnalyzingFiles}
          dllAnalyzingFiles={dllAnalyzingFiles}
          expandedDescriptions={expandedDescriptions}
          toggleDescription={toggleDescription}
          getLLMDescription={getLLMDescription}
          handleAnalyzeSingleFile={handleAnalyzeSingleFile}
          openReanalyzeModal={openReanalyzeModal}
          llmStatus={llmStatus}
          extractionStatus={extractionStatus}
          handleStartExtraction={handleStartExtraction}
          setExtractionMode={setExtractionMode}
          setExtractionPattern={setExtractionPattern}
        />
      )}

      {/* Extension Analysis Tab */}
      {activeTab === 'extensions' && (
        <ExtensionAnalysisTab extensionAnalysis={extensionAnalysis} />
      )}

      {/* Office Preview Tab */}
      {activeTab === 'office' && (
        <OfficePreviewTab
          filteredFiles={filteredFiles}
          officePreview={officePreview}
          setOfficePreview={setOfficePreview}
          officeParsing={officeParsing}
          setOfficeParsing={setOfficeParsing}
          officeError={officeError}
          setOfficeError={setOfficeError}
        />
      )}

      {/* Re-analysis Modal */}
      <ReanalyzeModal
        show={showReanalyzeModal}
        onClose={() => !reanalyzing && setShowReanalyzeModal(false)}
        targetFiles={reanalyzeTargetFiles}
        hint={reanalyzeHint}
        setHint={setReanalyzeHint}
        onSubmit={handleReanalyze}
        reanalyzing={reanalyzing}
        message={reanalyzeMessage}
      />
    </div>
  );
};

export default Files;
