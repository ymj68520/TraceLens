import { useEffect, useState, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';
import { startExtraction, pollExtractionStatus } from '../services/extractionService';
import { analyzeContent, startBatchAnalysis, pollBatchStatus, getLLMStatus } from '../services/llmService';
import { ingestTaskData, getGraphitiStatus } from '../services/graphitiService';
import { parseFile } from '../services/officeService';
import { getTaskResults } from '../services/taskService';

const Files = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

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
  const [llmAnalyzing, setLlmAnalyzing] = useState(false);
  const [llmAnalyzingFiles, setLlmAnalyzingFiles] = useState(new Set());
  const [llmBatchJobId, setLlmBatchJobId] = useState(null);
  const [llmProgress, setLlmProgress] = useState(0);
  const [llmMessage, setLlmMessage] = useState('');
  const [llmResults, setLlmResults] = useState({});
  const [existingLlmDescriptions, setExistingLlmDescriptions] = useState({});
  const [expandedDescriptions, setExpandedDescriptions] = useState(new Set());

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

  // Load existing LLM descriptions
  useEffect(() => {
    const loadLLMDescriptions = async () => {
      if (!taskId) return;
      try {
        const results = await getTaskResults(taskId);
        if (results.llm_results?.descriptions) {
          const descMap = {};
          results.llm_results.descriptions.forEach((desc) => {
            descMap[desc.file_path] = desc;
          });
          setExistingLlmDescriptions(descMap);
        }
      } catch (err) {
        console.error('Failed to load LLM descriptions:', err);
      }
    };
    loadLLMDescriptions();
  }, [taskId]);

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

  // Analyze single file
  const handleAnalyzeSingleFile = async (file, index) => {
    const filePath = file.path || file.file_path;
    if (!filePath) return;

    setLlmAnalyzingFiles(prev => new Set(prev).add(index));

    try {
      const result = await analyzeContent({
        filePath: filePath,
        modelType: 'text',
      });

      if (result.success) {
        setLlmResults(prev => ({
          ...prev,
          [filePath]: {
            summary: result.summary || result.description?.substring(0, 200),
            description: result.description,
            keywords: result.keywords,
          }
        }));
      }
    } catch (err) {
      console.error('Failed to analyze file:', err);
    } finally {
      setLlmAnalyzingFiles(prev => {
        const next = new Set(prev);
        next.delete(index);
        return next;
      });
    }
  };

  // Batch analyze selected files
  const handleBatchAnalyze = async () => {
    if (selectedFiles.size === 0) return;

    setLlmAnalyzing(true);
    setLlmProgress(0);
    setLlmMessage('启动批量分析...');

    try {
      const result = await startBatchAnalysis(taskId, {
        fileTypes: filterExtension ? filterExtension.split(',') : undefined,
        limit: selectedFiles.size,
        modelType: 'text',
      });

      if (result.job_id) {
        setLlmBatchJobId(result.job_id);

        await pollBatchStatus(result.job_id, (status) => {
          setLlmProgress(status.progress || 0);
          setLlmMessage(status.message || `已分析 ${status.processed || 0} 个文件`);
        }, 2000);

        setLlmMessage('批量分析完成！');
        // Reload LLM descriptions
        const results = await getTaskResults(taskId);
        if (results.llm_results?.descriptions) {
          const descMap = {};
          results.llm_results.descriptions.forEach((desc) => {
            descMap[desc.file_path] = desc;
          });
          setExistingLlmDescriptions(descMap);
        }
      }
    } catch (err) {
      console.error('Batch analysis failed:', err);
      setLlmMessage('批量分析失败: ' + (err.message || '未知错误'));
    } finally {
      setLlmAnalyzing(false);
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

  // Get LLM description for a file
  const getLLMDescription = (file) => {
    const filePath = file.path || file.file_path;
    return llmResults[filePath] || existingLlmDescriptions[filePath];
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
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">文件分析</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-300">分析和浏览分类后的文件</p>
        </div>

        <Card title="选择任务">
          <p className="text-gray-500 dark:text-gray-400">
            请从{' '}
            <a href="/tasks" className="text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300">
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
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">文件分析</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-300">任务: {currentTask?.image_path || taskId}</p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-gray-600 dark:text-gray-300">加载文件数据...</span>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">文件分析</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-300">任务: {currentTask?.image_path || taskId}</p>
        </div>

        <Card title="错误">
          <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-md">
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
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">文件分析</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">任务: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2 flex gap-2">
            <Badge variant="blue">{currentTask.status}</Badge>
            {llmStatus?.status === 'healthy' && <Badge variant="green">LLM 可用</Badge>}
            {graphitiStatus?.neo4j_connected && <Badge variant="purple">Graphiti 已连接</Badge>}
          </div>
        )}
      </div>

      {/* LLM Analysis Panel */}
      <Card title="🧠 AI 文件分析" className="bg-purple-50 dark:bg-purple-900/10 border-purple-200 dark:border-purple-800">
        <div className="space-y-4">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            选择文件后使用 AI 生成描述，并导入知识图谱进行关联分析。
          </p>

          {/* Service Status */}
          <div className="flex gap-4 text-sm">
            <span className={`flex items-center gap-1 ${llmStatus?.status === 'healthy' ? 'text-green-600' : 'text-red-600'}`}>
              <span className={`w-2 h-2 rounded-full ${llmStatus?.status === 'healthy' ? 'bg-green-500' : 'bg-red-500'}`} />
              LLM: {llmStatus?.status === 'healthy' ? '就绪' : '不可用'}
            </span>
            <span className={`flex items-center gap-1 ${graphitiStatus?.neo4j_connected ? 'text-green-600' : 'text-red-600'}`}>
              <span className={`w-2 h-2 rounded-full ${graphitiStatus?.neo4j_connected ? 'bg-green-500' : 'bg-red-500'}`} />
              Graphiti: {graphitiStatus?.neo4j_connected ? '已连接' : '未连接'}
            </span>
          </div>

          {/* Selection Stats & Actions */}
          <div className="flex items-center justify-between bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
            <div className="text-sm text-gray-700 dark:text-gray-300">
              已选择 <span className="font-bold text-purple-600">{selectedFiles.size}</span> 个文件
              {Object.keys(existingLlmDescriptions).length > 0 && (
                <span className="ml-4">
                  已有描述: <span className="font-bold text-green-600">{Object.keys(existingLlmDescriptions).length}</span>
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={handleBatchAnalyze}
                disabled={selectedFiles.size === 0 || llmAnalyzing || llmStatus?.status !== 'healthy'}
              >
                {llmAnalyzing ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    分析中 ({llmProgress}%)
                  </>
                ) : (
                  '🧠 批量分析'
                )}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleGraphitiIngest}
                disabled={graphitiIngesting || !graphitiStatus?.neo4j_connected}
              >
                {graphitiIngesting ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    导入中...
                  </>
                ) : (
                  '🕸️ 导入知识图谱'
                )}
              </Button>
            </div>
          </div>

          {/* LLM Progress */}
          {llmAnalyzing && (
            <div className="bg-white dark:bg-gray-800 p-3 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-gray-600 dark:text-gray-300">{llmMessage}</span>
                <span className="text-purple-600">{llmProgress}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2">
                <div className="bg-purple-600 h-2 rounded-full transition-all" style={{ width: `${llmProgress}%` }} />
              </div>
            </div>
          )}

          {/* Graphiti Message */}
          {graphitiMessage && (
            <div className={`p-3 rounded-lg text-sm ${graphitiIngesting ? 'bg-blue-50 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200' : 'bg-green-50 text-green-800 dark:bg-green-900/30 dark:text-green-200'}`}>
              {graphitiMessage}
            </div>
          )}
        </div>
      </Card>

      {/* File Extraction */}
      <Card title="📁 文件提取" className="bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800">
        <div className="space-y-4">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            从磁盘镜像提取文件以启用全文搜索和详细分析。
          </p>

          <div className="bg-white dark:bg-gray-800 p-4 rounded-md border border-gray-200 dark:border-gray-700">
            <h4 className="font-medium text-gray-900 dark:text-white mb-3">提取文件</h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">提取模式</label>
                <select
                  value={extractionMode}
                  onChange={(e) => setExtractionMode(e.target.value)}
                  disabled={extractionStatus === 'running'}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white"
                >
                  <option value="all">全部文件</option>
                  <option value="extension">按扩展名</option>
                  <option value="name">按名称模式</option>
                  <option value="deleted">仅删除文件</option>
                </select>
              </div>

              {(extractionMode === 'extension' || extractionMode === 'name') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {extractionMode === 'extension' ? '扩展名 (如: .log,.conf)' : '名称模式 (如: config*)'}
                  </label>
                  <input
                    type="text"
                    value={extractionPattern}
                    onChange={(e) => setExtractionPattern(e.target.value)}
                    disabled={extractionStatus === 'running'}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white"
                  />
                </div>
              )}
            </div>

            <div className="flex items-center gap-4 mb-4">
              {extractionMode === 'all' && (
                <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                  <input type="checkbox" checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} disabled={extractionStatus === 'running'} />
                  包含已删除文件
                </label>
              )}
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} disabled={extractionStatus === 'running'} />
                覆盖已存在文件
              </label>
            </div>

            <div className="flex items-center gap-4">
              <Button variant="primary" onClick={handleStartExtraction} disabled={extractionStatus === 'running'}>
                {extractionStatus === 'running' ? <><Spinner size="sm" className="mr-2" />提取中...</> : '🚀 开始提取'}
              </Button>
              {extractionStatus !== 'idle' && (
                <span className={`text-sm font-medium ${extractionStatus === 'completed' ? 'text-green-600' : extractionStatus === 'failed' ? 'text-red-600' : 'text-blue-600'}`}>
                  {extractionMessage}
                </span>
              )}
            </div>

            {(extractionStatus === 'running' || extractionStatus === 'pending') && (
              <div className="mt-4">
                <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2.5">
                  <div className="bg-blue-600 h-2.5 rounded-full transition-all" style={{ width: `${extractionProgress}%` }} />
                </div>
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>已提取: {extractedCount}</span>
                  {skippedCount > 0 && <span>已跳过: {skippedCount}</span>}
                </div>
              </div>
            )}

            {extractionStatus === 'completed' && (
              <div className="mt-4 p-3 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-md text-sm text-green-800 dark:text-green-200">
                ✅ 完成: 已提取 {extractedCount} 个文件，跳过 {skippedCount} 个
              </div>
            )}

            {extractionStatus === 'failed' && extractionError && (
              <div className="mt-4 p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-md text-sm text-red-800 dark:text-red-200">
                ❌ 失败: {extractionError}
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Filters */}
      <Card title="🔍 筛选文件">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">按扩展名</label>
            <input
              type="text"
              value={filterExtension}
              onChange={(e) => setFilterExtension(e.target.value)}
              placeholder=".jpg, .pdf, .doc"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">最小大小 (KB)</label>
            <input
              type="number"
              value={filterMinSize}
              onChange={(e) => setFilterMinSize(e.target.value)}
              placeholder="0"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">最大大小 (KB)</label>
            <input
              type="number"
              value={filterMaxSize}
              onChange={(e) => setFilterMaxSize(e.target.value)}
              placeholder="无限制"
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md dark:bg-gray-700 dark:text-white"
            />
          </div>
        </div>
        <div className="mt-3 text-sm text-gray-500 dark:text-gray-400">
          显示 {filteredFiles.length} / {largestFiles.length} 个文件
        </div>
      </Card>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700">
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
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400'
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
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">无文件</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="px-3 py-3 w-10">
                      <input
                        type="checkbox"
                        checked={selectAll}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                        className="h-4 w-4 text-purple-600 rounded"
                      />
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">#</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">名称</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">路径</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">大小</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">扩展名</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">AI 分析</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {filteredFiles.map((file, index) => {
                    const filePath = file.path || file.file_path;
                    const llmDesc = getLLMDescription(file);
                    const isAnalyzing = llmAnalyzingFiles.has(index);
                    const isExpanded = expandedDescriptions.has(filePath);

                    return (
                      <>
                        <tr key={index} className={`hover:bg-gray-50 dark:hover:bg-gray-700 ${selectedFiles.has(index) ? 'bg-purple-50 dark:bg-purple-900/20' : ''}`}>
                          <td className="px-3 py-4">
                            <input
                              type="checkbox"
                              checked={selectedFiles.has(index)}
                              onChange={() => handleFileSelect(index)}
                              className="h-4 w-4 text-purple-600 rounded"
                            />
                          </td>
                          <td className="px-4 py-4 text-sm font-medium text-gray-900 dark:text-white">#{index + 1}</td>
                          <td className="px-4 py-4 text-sm font-medium text-gray-900 dark:text-white">
                            {file.name || filePath?.split('/').pop() || '-'}
                          </td>
                          <td className="px-4 py-4 text-sm text-gray-600 dark:text-gray-300 max-w-xs truncate font-mono" title={filePath}>
                            {filePath || '-'}
                          </td>
                          <td className="px-4 py-4 text-sm text-gray-900 dark:text-white font-mono">
                            {formatFileSize(file.size || file.file_size)}
                          </td>
                          <td className="px-4 py-4 text-sm text-gray-500 dark:text-gray-400">
                            <Badge variant="blue">{file.extension || '-'}</Badge>
                          </td>
                          <td className="px-4 py-4">
                            <div className="flex items-center gap-2">
                              {llmDesc ? (
                                <button
                                  onClick={() => toggleDescription(filePath)}
                                  className="text-green-600 hover:text-green-800 text-sm flex items-center gap-1"
                                >
                                  ✅ {isExpanded ? '收起' : '查看'}
                                </button>
                              ) : (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleAnalyzeSingleFile(file, index)}
                                  disabled={isAnalyzing || llmStatus?.status !== 'healthy'}
                                >
                                  {isAnalyzing ? <Spinner size="sm" /> : '🧠'}
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                        {/* Expanded LLM Description Row */}
                        {isExpanded && llmDesc && (
                          <tr className="bg-gray-50 dark:bg-gray-900/50">
                            <td colSpan={7} className="px-6 py-4">
                              <div className="space-y-2">
                                {llmDesc.summary && (
                                  <div>
                                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">摘要: </span>
                                    <span className="text-sm text-gray-600 dark:text-gray-400">{llmDesc.summary}</span>
                                  </div>
                                )}
                                {llmDesc.keywords && (
                                  <div className="flex flex-wrap gap-1">
                                    {(typeof llmDesc.keywords === 'string' ? llmDesc.keywords.split(',') : llmDesc.keywords).map((kw, i) => (
                                      <span key={i} className="px-2 py-0.5 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded-full">
                                        {kw.trim()}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                {llmDesc.description && (
                                  <details className="text-sm">
                                    <summary className="cursor-pointer text-blue-600 hover:text-blue-800">查看完整描述</summary>
                                    <p className="mt-2 p-3 bg-white dark:bg-gray-800 rounded text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
                                      {llmDesc.description}
                                    </p>
                                  </details>
                                )}
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
              <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">扩展名</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">数量</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">总大小</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">占比</th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {extensionAnalysis.extension_analysis
                    .sort((a, b) => (b.file_count || 0) - (a.file_count || 0))
                    .map((ext, index) => {
                      const totalCount = extensionAnalysis.total_count || extensionAnalysis.extension_analysis.reduce((sum, e) => sum + (e.file_count || 0), 0);
                      const percentage = totalCount > 0 ? ((ext.file_count || 0) / totalCount * 100).toFixed(1) : '0.0';
                      return (
                        <tr key={index} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                          <td className="px-6 py-4">
                            <Badge variant="blue">{ext.extension || '(无扩展名)'}</Badge>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-900 dark:text-white">{ext.file_count || 0}</td>
                          <td className="px-6 py-4 text-sm text-gray-900 dark:text-white font-mono">{formatFileSize(ext.total_size || 0)}</td>
                          <td className="px-6 py-4 text-sm text-gray-900 dark:text-white">{percentage}%</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">无扩展名数据</div>
          )}
        </Card>
      )}

      {/* Office Preview Tab */}
      {activeTab === 'office' && (
        <Card title="📄 Office 文档预览">
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              选择一个 Office 文件 (PPT, Excel) 解析并预览内容。支持 .pptx, .xlsx, .xls 格式。
            </p>
            {/* File selector for Office files */}
            <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">选择文件</h4>
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
                        className="w-full text-left px-3 py-2 rounded hover:bg-blue-50 dark:hover:bg-blue-900/20 text-sm text-gray-700 dark:text-gray-300 flex items-center gap-2"
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
                    <p className="text-gray-400 text-sm py-4 text-center">无 Office 文件</p>
                  )}
              </div>
            </div>

            {officeParsing && (
              <div className="flex items-center justify-center py-8">
                <Spinner size="lg" />
                <span className="ml-3 text-gray-600 dark:text-gray-300">解析中...</span>
              </div>
            )}

            {officeError && (
              <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded text-sm">
                ❌ {officeError}
              </div>
            )}

            {officePreview && (
              <div className="bg-white dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
                <h4 className="font-medium text-gray-900 dark:text-white mb-3">
                  📄 {officePreview.file?.name || '文档内容'}
                </h4>
                {/* Slides / Sheets */}
                {officePreview.slides && (
                  <div className="space-y-3">
                    <p className="text-sm text-gray-500">幻灯片: {officePreview.slides.length} 页</p>
                    {officePreview.slides.map((slide, i) => (
                      <div key={i} className="p-3 bg-gray-50 dark:bg-gray-900 rounded border">
                        <p className="text-xs text-gray-400 mb-1">第 {i + 1} 页</p>
                        <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap">{slide.text || slide.content || '(无文本)'}</p>
                      </div>
                    ))}
                  </div>
                )}
                {officePreview.sheets && (
                  <div className="space-y-3">
                    <p className="text-sm text-gray-500">工作表: {officePreview.sheets.length} 个</p>
                    {officePreview.sheets.map((sheet, i) => (
                      <div key={i} className="p-3 bg-gray-50 dark:bg-gray-900 rounded border">
                        <p className="text-xs text-gray-400 mb-1">{sheet.name || `工作表 ${i + 1}`}</p>
                        {sheet.data && sheet.data.length > 0 ? (
                          <div className="overflow-x-auto">
                            <table className="text-xs">
                              <tbody>
                                {sheet.data.slice(0, 20).map((row, ri) => (
                                  <tr key={ri}>
                                    {(Array.isArray(row) ? row : [row]).map((cell, ci) => (
                                      <td key={ci} className="px-2 py-1 border border-gray-200 dark:border-gray-600">{String(cell ?? '')}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {sheet.data.length > 20 && <p className="text-xs text-gray-400 mt-1">… 还有 {sheet.data.length - 20} 行</p>}
                          </div>
                        ) : (
                          <p className="text-sm text-gray-400">(无数据)</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {/* Raw text fallback */}
                {officePreview.text && !officePreview.slides && !officePreview.sheets && (
                  <pre className="text-sm text-gray-800 dark:text-gray-200 bg-gray-50 dark:bg-gray-900 p-4 rounded overflow-auto max-h-96 whitespace-pre-wrap">
                    {officePreview.text}
                  </pre>
                )}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
};

export default Files;
