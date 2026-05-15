import { motion } from 'framer-motion';
import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { fetchTasks } from '../store/taskSlice';
import { setBatchJob, updateBatchProgress, clearBatchJob, setRefreshFlag } from '../store/intelligenceSlice';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';
import { startExtraction, pollExtractionStatus } from '../services/extractionService';
import { analyzeContent, startBatchAnalysis, pollBatchStatus, getLLMStatus, getBatchStatus } from '../services/llmService';
import { reanalyzeFiles, getCaseAnalysisStatus } from '../services/caseAnalysisService';
import { ingestTaskData, getGraphitiStatus } from '../services/graphitiService';
import { parseFile } from '../services/officeService';
import { getTaskResults } from '../services/taskService';

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
  const [llmAnalyzingFiles, setLlmAnalyzingFiles] = useState(new Set());
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
    const response = await fetch('/api/llm/analyze/dll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: filePath,
        files_db_path: filesDbPath
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'DLL分析失败');
    }

    return await response.json();
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

    // Check file extension only (no size limits)
    const archiveExtensions = ['zip', 'tar', 'gz', 'tgz', 'rar', '7z'];
    const isArchive = archiveExtensions.includes(extension);

    setLlmAnalyzingFiles(prev => new Set(prev).add(index));

    try {
      let result;

      // DLL/EXE/SYS file analysis
      if (isDLL) {
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
            errorMsg = `DLL分析服务未运行\n\n提示：\n1. 请确保 C++ 服务已启动: ./build/forensic_analyzer --http-server 8080\n2. 请确保 Python 服务已启动: python -m python_service.httpserver.main\n3. 或使用启动脚本: ./scripts/start_services.sh`;
          } else if (dllErr.response?.status === 400 || dllErr.response?.status === 404) {
            const detail = dllErr.response?.data?.detail || '';
            if (detail.includes('File not found') || detail.includes('not found')) {
              errorMsg = `❌ DLL文件未找到\n\n${detail}\n\n建议：使用"批量提取"功能先提取文件`;
            }
          }

          alert(`DLL分析失败: ${errorMsg}\n\n文件: ${file.name || filePath}\n类型: ${extension.toUpperCase()}\n大小: ${(fileSize / 1024).toFixed(1)} KB`);
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

  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
  };

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
      {/* Header */}
      <div>
        <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">文件分析</motion.h1>
        <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2 flex gap-2">
            <Badge variant="blue">{currentTask.status}</Badge>
            {(llmStatus?.status === 'healthy' || llmStatus?.status === 'available') && <Badge variant="green">LLM 可用</Badge>}
            {graphitiStatus?.neo4j_connected && <Badge variant="purple">Graphiti 已连接</Badge>}
          </div>
        )}
      </div>

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
            {/* Column 1: Filters (4/12) */}
            <div className="lg:col-span-4 space-y-4 pr-0 lg:pr-6 lg:border-r border-slate-100 dark:border-slate-700">
              <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">🔍 筛选器</h4>
              <div className="space-y-3">
                <div className="relative">
                  <span className="absolute left-3 top-2.5 text-slate-400">🏷️</span>
                  <input
                    type="text"
                    value={filterExtension}
                    onChange={(e) => setFilterExtension(e.target.value)}
                    placeholder="扩展名 (如 .jpg)"
                    className="w-full pl-9 pr-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="number"
                    value={filterMinSize}
                    onChange={(e) => setFilterMinSize(e.target.value)}
                    placeholder="最小 KB"
                    className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
                  />
                  <input
                    type="number"
                    value={filterMaxSize}
                    onChange={(e) => setFilterMaxSize(e.target.value)}
                    placeholder="最大 KB"
                    className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white"
                  />
                </div>
              </div>
            </div>

            {/* Column 2: Extraction & AI Actions (8/12) */}
            <div className="lg:col-span-8 space-y-6">
              {/* Row 1: Extract Controls */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">📁 数据提取</h4>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                      <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} disabled={extractionStatus === 'running'} className="rounded text-primary-600 h-3.5 w-3.5" />
                      覆盖
                    </label>
                    <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                      <input type="checkbox" checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} disabled={extractionStatus === 'running'} className="rounded text-primary-600 h-3.5 w-3.5" />
                      含已删除
                    </label>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" size="sm" onClick={handleStartExtraction} disabled={extractionStatus === 'running'}>
                    {extractionStatus === 'running' ? <Spinner size="sm" /> : '🚀 提取所有匹配'}
                  </Button>
                  <Button variant="outline" size="sm" onClick={async () => {
                    const names = [...selectedFiles].map(idx => filteredFiles[idx].name || (filteredFiles[idx].path || filteredFiles[idx].file_path)?.split('/').pop()).filter(Boolean);
                    if (names.length > 0) { setExtractionMode('name'); setExtractionPattern(names.join(',')); handleStartExtraction(); }
                  }} disabled={selectedFiles.size === 0 || extractionStatus === 'running'}>
                    📥 提取选中 ({selectedFiles.size})
                  </Button>
                  {extractionStatus !== 'idle' && (
                    <div className="flex-1 flex items-center gap-3 px-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg min-w-[200px]">
                      <div className="flex-1 h-1.5 bg-blue-200 dark:bg-blue-800 rounded-full overflow-hidden">
                        <div className="bg-blue-600 h-full transition-all" style={{ width: `${extractionProgress}%` }} />
                      </div>
                      <span className="text-[10px] font-mono text-blue-700 dark:text-blue-300 whitespace-nowrap">{extractionMessage}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Row 2: AI & KG Actions */}
              <div className="space-y-3 pt-4 border-t border-slate-100 dark:border-slate-700">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">🧠 AI 取证 & 建模</h4>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleBatchAnalyze}
                    disabled={isBatchRunning || (llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available')}
                    className="bg-purple-600 hover:bg-purple-700 text-white"
                    title={selectedFiles.size > 0 ? `将分析选中的 ${selectedFiles.size} 个文件` : `将分析当前筛选结果中的所有文件`}
                  >
                    {isBatchRunning ? <Spinner size="sm" /> : '🧠 批量分析'}
                    {selectedFiles.size > 0 && (
                      <span className="ml-1.5 px-1.5 py-0.5 text-xs bg-white/20 rounded">
                        {selectedFiles.size}
                      </span>
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const paths = [...selectedFiles].map(idx => filteredFiles[idx].path || filteredFiles[idx].file_path).filter(Boolean);
                      if (paths.length > 0) openReanalyzeModal(paths);
                    }}
                    disabled={selectedFiles.size === 0 || (llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available')}
                  >
                    🔄 批量重新分析
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleGraphitiIngest}
                    disabled={graphitiIngesting || !graphitiStatus?.neo4j_connected}
                  >
                    {graphitiIngesting ? <Spinner size="sm" /> : '🕸️ 导入图谱'}
                  </Button>

                  {/* AI Progress */}
                  {(isBatchRunning || graphitiIngesting || graphitiMessage) && (
                    <div className="flex-1 flex items-center gap-3 px-3 bg-purple-50 dark:bg-purple-900/20 rounded-lg min-w-[200px]">
                      {isBatchRunning && (
                        <>
                          <div className="flex-1 h-1.5 bg-purple-200 dark:bg-purple-800 rounded-full overflow-hidden">
                            <div className="bg-purple-600 h-full transition-all" style={{ width: `${activeBatch?.progress || 0}%` }} />
                          </div>
                          <span className="text-[10px] font-mono text-purple-700 dark:text-purple-300 whitespace-nowrap">{activeBatch?.message || ""}</span>
                        </>
                      )}
                      {!isBatchRunning && graphitiMessage && (
                        <span className="text-xs text-purple-700 dark:text-purple-300 truncate">
                          {graphitiIngesting && <Spinner size="sm" className="mr-2" />}
                          {graphitiMessage}
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
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
        <Card title={`文件列表 (${filteredFiles.length})`}>
          {filteredFiles.length === 0 ? (
            <div className="text-center py-12 text-slate-500 dark:text-slate-400">无文件</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                <thead className="bg-slate-50 dark:bg-slate-800">
                  <tr>
                    <th className="px-3 py-3 w-10">
                      <input
                        type="checkbox"
                        checked={selectAll}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                        className="h-4 w-4 text-purple-600 rounded"
                      />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">#</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">名称</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">路径</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">大小</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">扩展名</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">AI 分析</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">操作</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                  {filteredFiles.map((file, index) => {
                    const filePath = file.path || file.file_path;
                    const fileName = file.name || filePath?.split('/').pop() || '-';
                    const llmDesc = getLLMDescription(file);
                    const isAnalyzing = llmAnalyzingFiles.has(index);
                    const isExpanded = expandedDescriptions.has(filePath);
                    const hasDescription = llmDesc && (llmDesc.summary || llmDesc.description);

                    return (
                      <>
                        <tr key={index} className={`hover:bg-slate-50 dark:hover:bg-slate-700 ${selectedFiles.has(index) ? 'bg-purple-50 dark:bg-purple-900/20' : ''}`}>
                          <td className="px-3 py-4">
                            <input
                              type="checkbox"
                              checked={selectedFiles.has(index)}
                              onChange={() => handleFileSelect(index)}
                              className="h-4 w-4 text-purple-600 rounded"
                            />
                          </td>
                          <td className="px-4 py-4 text-sm font-medium text-slate-900 dark:text-white">#{index + 1}</td>
                          <td className="px-4 py-4 text-sm font-medium text-slate-900 dark:text-white">
                            {fileName}
                          </td>
                          <td className="px-4 py-4 text-sm text-slate-600 dark:text-slate-300 max-w-xs truncate font-mono" title={filePath}>
                            {filePath || '-'}
                          </td>
                          <td className="px-4 py-4 text-sm text-slate-900 dark:text-white font-mono">
                            {formatFileSize(file.size || file.file_size)}
                          </td>
                          <td className="px-4 py-4 text-sm text-slate-500 dark:text-slate-400">
                            <Badge variant="blue">{file.extension || '-'}</Badge>
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex flex-col gap-2">
                              {/* ... (existing LLM analysis UI) */}
                              {hasDescription ? (
                                <div className="max-w-md">
                                  <div className="flex items-start gap-2">
                                    <span className="text-green-500 mt-0.5">✨</span>
                                    <div className="flex-1 min-w-0">
                                      {/* DLL Threat Level Badge */}
                                      {llmDesc.isDLLAnalysis && llmDesc.threatLevel && (
                                        <div className="mb-1">
                                          {(() => {
                                            const levelConfig = {
                                              'low': { label: '低风险', variant: 'green', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
                                              'medium': { label: '中风险', variant: 'yellow', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
                                              'high': { label: '高风险', variant: 'orange', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
                                              'critical': { label: '严重', variant: 'red', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
                                              '严重': { label: '严重', variant: 'red', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
                                              '高': { label: '高风险', variant: 'orange', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
                                              '中': { label: '中风险', variant: 'yellow', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
                                              '低': { label: '低风险', variant: 'green', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
                                            };
                                            const config = levelConfig[llmDesc.threatLevel] || { label: llmDesc.threatLevel, variant: 'blue', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' };
                                            return <span className={`inline-block px-2 py-0.5 text-xs font-semibold rounded-full ${config.className}`}>{config.label}</span>;
                                          })()}
                                          {llmDesc.confidence && <span className="ml-1.5 text-xs text-slate-500">置信度: {llmDesc.confidence}%</span>}
                                        </div>
                                      )}
                                      {/* Summary - always visible */}
                                      {llmDesc.summary && (
                                        <p className="text-sm text-slate-600 dark:text-slate-300 line-clamp-2 mb-1">
                                          {llmDesc.summary}
                                        </p>
                                      )}

                                      {/* Keywords */}
                                      {llmDesc.keywords && llmDesc.keywords.length > 0 && (
                                        <div className="flex flex-wrap gap-1 mb-1">
                                          {(typeof llmDesc.keywords === 'string'
                                            ? llmDesc.keywords.split(',')
                                            : llmDesc.keywords
                                          ).slice(0, 3).map((kw, i) => (
                                            <span key={i} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                              {kw.trim()}
                                            </span>
                                          ))}
                                          {(typeof llmDesc.keywords === 'string'
                                            ? llmDesc.keywords.split(',')
                                            : llmDesc.keywords
                                          ).length > 3 && (
                                              <span className="text-xs text-slate-500">
                                                +{(typeof llmDesc.keywords === 'string'
                                                  ? llmDesc.keywords.split(',')
                                                  : llmDesc.keywords
                                                ).length - 3} more
                                              </span>
                                            )}
                                        </div>
                                      )}

                                      {/* Expand/Collapse button for full description */}
                                      {llmDesc.description && (
                                        <button
                                          onClick={() => toggleDescription(filePath)}
                                          className="text-xs text-purple-600 hover:text-purple-800 dark:text-purple-400 dark:hover:text-purple-300"
                                        >
                                          {isExpanded ? '收起详情 ▲' : '展开详情 ▼'}
                                        </button>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              ) : (
                                /* Analyze Button - only show if no description */
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleAnalyzeSingleFile(file, index)}
                                  disabled={isAnalyzing || (llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available')}
                                  className="text-xs"
                                >
                                  {isAnalyzing ? (
                                    <>
                                      <Spinner size="sm" />
                                      <span className="ml-2">分析中...</span>
                                    </>
                                  ) : (
                                    '🧠 AI 分析'
                                  )}
                                </Button>
                              )}
                              {dllAnalyzingFiles.has(index) && !isAnalyzing && (
                                <div className="analyzing-indicator text-xs text-blue-600 dark:text-blue-400 mt-1">
                                  🔍 DLL分析中...
                                </div>
                              )}
                              {/* Re-analyze button - shown when description exists */}
                              {hasDescription && (
                                <button
                                  onClick={() => openReanalyzeModal([filePath])}
                                  disabled={llmStatus?.status !== 'healthy' && llmStatus?.status !== 'available'}
                                  className="text-xs text-amber-600 hover:text-amber-800 dark:text-amber-400 dark:hover:text-amber-300 flex items-center gap-1 mt-1"
                                >
                                  🔄 重新分析
                                </button>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-4 text-sm font-medium">
                            <button
                              onClick={() => {
                                setExtractionMode('name');
                                setExtractionPattern(fileName);
                                handleStartExtraction();
                              }}
                              disabled={extractionStatus === 'running'}
                              className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1 p-2 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
                              title={`从镜像中提取 ${fileName}`}
                              aria-label={`提取 ${fileName}`}
                            >
                              <span className="text-lg">📥</span>
                              <span>提取</span>
                            </button>
                          </td>
                        </tr>

                        {/* Expanded Full Description Row */}
                        {isExpanded && hasDescription && llmDesc.description && (
                          <tr className="bg-purple-50 dark:bg-purple-900/20">
                            <td colSpan={7} className="px-6 py-4">
                              <div className="space-y-3">
                                <div className="flex items-center gap-2 mb-2">
                                  <span className="text-lg">📝</span>
                                  <h4 className="font-medium text-slate-900 dark:text-white">AI 完整分析</h4>
                                </div>

                                {/* Summary */}
                                {llmDesc.summary && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">摘要</span>
                                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                                      {llmDesc.summary}
                                    </p>
                                  </div>
                                )}

                                {/* Threat Level & Confidence (DLL analysis) */}
                                {llmDesc.isDLLAnalysis && llmDesc.threatLevel && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">威胁评估</span>
                                    <div className="mt-2 flex items-center gap-3">
                                      {(() => {
                                        const levelConfig = {
                                          'low': { label: '低风险', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
                                          'medium': { label: '中风险', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
                                          'high': { label: '高风险', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
                                          'critical': { label: '严重', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
                                          '严重': { label: '严重', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
                                          '高': { label: '高风险', className: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200' },
                                          '中': { label: '中风险', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
                                          '低': { label: '低风险', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
                                        };
                                        const config = levelConfig[llmDesc.threatLevel] || { label: llmDesc.threatLevel, className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' };
                                        return (
                                          <>
                                            <span className={`inline-block px-3 py-1 text-sm font-bold rounded-full ${config.className}`}>
                                              {config.label}
                                            </span>
                                            {llmDesc.confidence !== undefined && (
                                              <span className="text-sm text-slate-600 dark:text-slate-300">
                                                置信度: <span className="font-semibold">{llmDesc.confidence}%</span>
                                              </span>
                                            )}
                                          </>
                                        );
                                      })()}
                                    </div>
                                  </div>
                                )}

                                {/* Suspicious Behaviors (DLL analysis) */}
                                {llmDesc.isDLLAnalysis && llmDesc.suspiciousBehaviors && llmDesc.suspiciousBehaviors.length > 0 && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">可疑行为</span>
                                    <ul className="mt-2 space-y-1">
                                      {llmDesc.suspiciousBehaviors.map((behavior, i) => (
                                        <li key={i} className="text-sm text-slate-700 dark:text-slate-300 flex items-start gap-2">
                                          <span className="text-orange-500 mt-1">&#9679;</span>
                                          <span>{behavior}</span>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}

                                {/* MITRE ATT&CK Techniques (DLL analysis) */}
                                {llmDesc.isDLLAnalysis && llmDesc.mitreTechniques && llmDesc.mitreTechniques.length > 0 && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">MITRE ATT&amp;CK 技术</span>
                                    <div className="mt-2 flex flex-wrap gap-1">
                                      {llmDesc.mitreTechniques.map((tech, i) => (
                                        <span key={i} className="px-2 py-1 text-xs bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 rounded-full font-mono" title={tech.name || tech}>
                                          {typeof tech === 'string' ? tech : (tech.id || tech)}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* Recommendations (DLL analysis) */}
                                {llmDesc.isDLLAnalysis && llmDesc.recommendations && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">处置建议</span>
                                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                                      {llmDesc.recommendations}
                                    </p>
                                  </div>
                                )}

                                {/* Full Description */}
                                {llmDesc.description && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">详细描述</span>
                                    <p className="mt-1 text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                                      {llmDesc.description}
                                    </p>
                                  </div>
                                )}

                                {/* All Keywords */}
                                {llmDesc.keywords && llmDesc.keywords.length > 0 && (
                                  <div className="bg-white dark:bg-slate-800 p-3 rounded-lg">
                                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">关键词</span>
                                    <div className="mt-2 flex flex-wrap gap-1">
                                      {(typeof llmDesc.keywords === 'string'
                                        ? llmDesc.keywords.split(',')
                                        : llmDesc.keywords
                                      ).map((kw, i) => (
                                        <span key={i} className="px-2 py-1 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                          {kw.trim()}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {/* Metadata */}
                                <div className="text-xs text-slate-500 dark:text-slate-400">
                                  {llmDesc.model && <span>模型: {llmDesc.model} | </span>}
                                  {llmDesc.timestamp && <span>分析时间: {new Date(llmDesc.timestamp).toLocaleString()}</span>}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Extension Analysis Tab */}
      {activeTab === 'extensions' && extensionAnalysis && (
        <Card title="按扩展名分布">
          {extensionAnalysis.extension_analysis && extensionAnalysis.extension_analysis.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
                <thead className="bg-slate-50 dark:bg-slate-800">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">扩展名</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">数量</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">总大小</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase">占比</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                  {extensionAnalysis.extension_analysis
                    .sort((a, b) => (b.file_count || 0) - (a.file_count || 0))
                    .map((ext, index) => {
                      const totalCount = extensionAnalysis.total_count || extensionAnalysis.extension_analysis.reduce((sum, e) => sum + (e.file_count || 0), 0);
                      const percentage = totalCount > 0 ? ((ext.file_count || 0) / totalCount * 100).toFixed(1) : '0.0';
                      return (
                        <tr key={index} className="hover:bg-slate-50 dark:hover:bg-slate-700">
                          <td className="px-6 py-4">
                            <Badge variant="blue">{ext.extension || '(无扩展名)'}</Badge>
                          </td>
                          <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">{ext.file_count || 0}</td>
                          <td className="px-6 py-4 text-sm text-slate-900 dark:text-white font-mono">{formatFileSize(ext.total_size || 0)}</td>
                          <td className="px-6 py-4 text-sm text-slate-900 dark:text-white">{percentage}%</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12 text-slate-500 dark:text-slate-400">无扩展名数据</div>
          )}
        </Card>
      )}

      {/* Office Preview Tab */}
      {activeTab === 'office' && (
        <Card title="📄 Office 文档预览">
          <div className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              选择一个 Office 文件 (PPT, Excel) 解析并预览内容。支持 .pptx, .xlsx, .xls 格式。
            </p>
            {/* File selector for Office files */}
            <div className="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700">
              <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-3">选择文件</h4>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {filteredFiles
                  .filter(f => {
                    const ext = (f.extension || '').toLowerCase();
                    return ['.pptx', '.ppt', '.xlsx', '.xls', '.docx', '.doc'].includes(ext);
                  })
                  .map((file, idx) => {
                    const filePath = file.path || file.file_path;
                    return (
                      <button
                        key={idx}
                        onClick={async () => {
                          setOfficeParsing(true);
                          setOfficeError(null);
                          setOfficePreview(null);
                          try {
                            const result = await parseFile(filePath);
                            setOfficePreview({ file, ...result });
                          } catch (err) {
                            setOfficeError(err.message || '解析失败');
                          } finally {
                            setOfficeParsing(false);
                          }
                        }}
                        disabled={officeParsing}
                        className="w-full text-left px-3 py-2 rounded hover:bg-blue-50 dark:hover:bg-blue-900/20 text-sm text-slate-700 dark:text-slate-300 flex items-center gap-2"
                      >
                        <Badge variant="blue">{file.extension}</Badge>
                        <span className="truncate">{file.name || filePath?.split('/').pop()}</span>
                      </button>
                    );
                  })}
                {filteredFiles.filter(f => {
                  const ext = (f.extension || '').toLowerCase();
                  return ['.pptx', '.ppt', '.xlsx', '.xls', '.docx', '.doc'].includes(ext);
                }).length === 0 && (
                    <p className="text-slate-400 text-sm py-4 text-center">无 Office 文件</p>
                  )}
              </div>
            </div>

            {officeParsing && (
              <div className="flex items-center justify-center py-8">
                <Spinner size="lg" />
                <span className="ml-3 text-slate-600 dark:text-slate-300">解析中...</span>
              </div>
            )}

            {officeError && (
              <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded text-sm">
                ❌ {officeError}
              </div>
            )}

            {officePreview && (
              <div className="bg-white dark:bg-slate-800 p-4 rounded-xl border border-slate-200 dark:border-slate-700">
                <h4 className="font-medium text-slate-900 dark:text-white mb-3">
                  📄 {officePreview.file?.name || '文档内容'}
                </h4>
                {/* Slides / Sheets */}
                {officePreview.slides && (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-500">幻灯片: {officePreview.slides.length} 页</p>
                    {officePreview.slides.map((slide, i) => (
                      <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                        <p className="text-xs text-slate-400 mb-1">第 {i + 1} 页</p>
                        <p className="text-sm text-slate-800 dark:text-slate-200 whitespace-pre-wrap">{slide.text || slide.content || '(无文本)'}</p>
                      </div>
                    ))}
                  </div>
                )}
                {officePreview.sheets && (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-500">工作表: {officePreview.sheets.length} 个</p>
                    {officePreview.sheets.map((sheet, i) => (
                      <div key={i} className="p-3 bg-slate-50 dark:bg-slate-900 rounded border">
                        <p className="text-xs text-slate-400 mb-1">{sheet.name || `工作表 ${i + 1}`}</p>
                        {sheet.data && sheet.data.length > 0 ? (
                          <div className="overflow-x-auto">
                            <table className="text-xs">
                              <tbody>
                                {sheet.data.slice(0, 20).map((row, ri) => (
                                  <tr key={ri}>
                                    {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                                      <td key={ci} className="px-2 py-1 border border-slate-200 dark:border-slate-600">{String(cell ?? '')}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {sheet.data.length > 20 && <p className="text-xs text-slate-400 mt-1">… 还有 {sheet.data.length - 20} 行</p>}
                          </div>
                        ) : (
                          <p className="text-sm text-slate-400">(无数据)</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {/* Raw text fallback */}
                {officePreview.text && !officePreview.slides && !officePreview.sheets && (
                  <pre className="text-sm text-slate-800 dark:text-slate-200 bg-slate-50 dark:bg-slate-900 p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                    {officePreview.text}
                  </pre>
                )}
              </div>
            )}
          </div>
        </Card>
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

// Re-analysis Modal
const ReanalyzeModal = ({ show, onClose, targetFiles, hint, setHint, onSubmit, reanalyzing, message }) => {
  if (!show) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-lg w-full mx-4 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
            🔄 重新分析文件
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
          >
            ✕
          </button>
        </div>

        <div className="mb-4">
          <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
            将对 <span className="font-bold text-purple-600">{targetFiles.length}</span> 个文件进行二次分析，结合案情描述和知识图谱上下文。
          </p>
          {targetFiles.length <= 3 && (
            <div className="space-y-1 mb-3">
              {targetFiles.map((f, i) => (
                <div key={i} className="text-xs font-mono text-slate-500 dark:text-slate-400 truncate">
                  📄 {f}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="mb-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            补充描述 / 分析提示
          </label>
          <textarea
            value={hint}
            onChange={(e) => setHint(e.target.value)}
            placeholder="请输入对该文件的额外描述或分析方向，例如：请重点关注转账记录和可疑联系人..."
            className="w-full h-28 px-4 py-3 border border-slate-300 dark:border-slate-600 rounded-xl dark:bg-slate-700 dark:text-white text-sm resize-none focus:ring-2 focus:ring-purple-500"
            disabled={reanalyzing}
          />
        </div>

        {message && (
          <div className={`mb-4 p-3 rounded-xl text-sm ${message.startsWith('✅') ? 'bg-green-50 text-green-800 dark:bg-green-900/30 dark:text-green-200' :
            message.startsWith('❌') ? 'bg-red-50 text-red-800 dark:bg-red-900/30 dark:text-red-200' :
              'bg-blue-50 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200'
            }`}>
            {message}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-xl"
            disabled={reanalyzing}
          >
            取消
          </button>
          <button
            onClick={onSubmit}
            disabled={reanalyzing || !hint.trim()}
            className={`px-6 py-2 rounded-xl text-sm font-medium transition-all ${reanalyzing || !hint.trim()
              ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
              : 'bg-gradient-to-r from-amber-500 to-orange-500 text-white hover:from-amber-600 hover:to-orange-600 shadow-lg'
              }`}
          >
            {reanalyzing ? (
              <span className="flex items-center">
                <Spinner size="sm" />
                <span className="ml-2">分析中...</span>
              </span>
            ) : (
              '🔄 开始重新分析'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Files;
