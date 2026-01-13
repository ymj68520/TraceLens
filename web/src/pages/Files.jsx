import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';
import { startExtraction, pollExtractionStatus } from '../services/extractionService';

const Files = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [largestFiles, setLargestFiles] = useState([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('largest');

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

  const currentTask = tasks.find((t) => t.id === taskId);

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

      // Poll for status
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
    console.log('[FILES PAGE] Files component mounted/updated. Version: 2025-01-13-12-43');
    if (!taskId) {
      setError('No task ID provided. Please select a task from the Tasks page.');
      return;
    }

    const fetchData = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch data separately to handle errors independently
        let largestData = [];
        let extensionData = null;

        try {
          largestData = await getLargestFiles(taskId, 50);
          console.log('Largest files response:', largestData);
        } catch (err) {
          console.error('Failed to fetch largest files:', err);
          largestData = [];
        }

        try {
          extensionData = await getExtensionAnalysis(taskId);
          console.log('Extension analysis response:', extensionData);
          console.log('First extension:', JSON.stringify(extensionData.extension_analysis?.[0], null, 2));
          console.log('All extensions:', JSON.stringify(extensionData.extension_analysis, null, 2));
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

  // Format file size
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
          <h1 className="text-3xl font-bold text-gray-900">File Analysis</h1>
          <p className="mt-2 text-gray-600">Analyze and explore classified files</p>
        </div>

        <Card title="Select a Task">
          <p className="text-gray-500">
            Select a completed task from the{' '}
            <a href="/tasks" className="text-blue-600 hover:text-blue-800">
              Tasks page
            </a>{' '}
            or use the task selector in the top bar to view file analysis.
          </p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">File Analysis</h1>
          <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-gray-600">Loading file data...</span>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">File Analysis</h1>
          <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        </div>

        <Card title="Error">
          <div className="p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-red-800">{error}</p>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">File Analysis</h1>
        <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
          </div>
        )}
      </div>

      {/* File Extraction */}
      <Card title="📁 File Extraction" className="bg-blue-50 border-blue-200">
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Extract files from the disk image to enable full-text search and detailed analysis.
          </p>

          {/* Extraction Controls */}
          <div className="bg-white p-4 rounded-md border border-gray-200">
            <h4 className="font-medium text-gray-900 mb-3">Extract Files</h4>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              {/* Mode Selector */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Extraction Mode
                </label>
                <select
                  value={extractionMode}
                  onChange={(e) => setExtractionMode(e.target.value)}
                  disabled={extractionStatus === 'running'}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                >
                  <option value="all">All Files</option>
                  <option value="extension">By Extension</option>
                  <option value="name">By Name Pattern</option>
                  <option value="deleted">Deleted Files Only</option>
                </select>
              </div>

              {/* Pattern Input (for extension/name modes) */}
              {(extractionMode === 'extension' || extractionMode === 'name') && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {extractionMode === 'extension' ? 'Extensions (e.g., .log,.conf)' : 'Name Pattern (e.g., config*)'}
                  </label>
                  <input
                    type="text"
                    value={extractionPattern}
                    onChange={(e) => setExtractionPattern(e.target.value)}
                    disabled={extractionStatus === 'running'}
                    placeholder={extractionMode === 'extension' ? '.log,.txt,.conf' : '*.log'}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
              )}

              {/* Options */}
              <div className="flex flex-col space-y-2 mb-4">
                {extractionMode === 'all' && (
                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      id="includeDeleted"
                      checked={includeDeleted}
                      onChange={(e) => setIncludeDeleted(e.target.checked)}
                      disabled={extractionStatus === 'running'}
                      className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                    />
                    <label htmlFor="includeDeleted" className="ml-2 text-sm text-gray-700">
                      Include deleted files
                    </label>
                  </div>
                )}

                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="overwrite"
                    checked={overwrite}
                    onChange={(e) => setOverwrite(e.target.checked)}
                    disabled={extractionStatus === 'running'}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="overwrite" className="ml-2 text-sm text-gray-700">
                    Overwrite existing files
                  </label>
                </div>
              </div>
            </div>

            {/* Extract Button */}
            <div className="flex items-center space-x-4">
              <Button
                variant="primary"
                onClick={handleStartExtraction}
                disabled={extractionStatus === 'running' || extractionStatus === 'pending'}
              >
                {extractionStatus === 'running' || extractionStatus === 'pending' ? (
                  <>
                    <Spinner size="sm" className="mr-2" />
                    Extracting...
                  </>
                ) : (
                  '🚀 Start Extraction'
                )}
              </Button>

              {extractionStatus && extractionStatus !== 'idle' && (
                <span className={`text-sm font-medium ${extractionStatus === 'completed' ? 'text-green-600' :
                  extractionStatus === 'failed' ? 'text-red-600' :
                    'text-blue-600'
                  }`}>
                  {extractionMessage}
                </span>
              )}
            </div>

            {/* Progress Bar */}
            {(extractionStatus === 'running' || extractionStatus === 'pending') && (
              <div className="mt-4">
                <div className="flex justify-between text-sm text-gray-600 mb-1">
                  <span>Progress</span>
                  <span>{extractionProgress}%</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-2.5">
                  <div
                    className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
                    style={{ width: `${extractionProgress}%` }}
                  ></div>
                </div>
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>Extracted: {extractedCount}</span>
                  {skippedCount > 0 && <span>Skipped: {skippedCount}</span>}
                </div>
              </div>
            )}

            {/* Success Message */}
            {extractionStatus === 'completed' && (
              <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-md">
                <p className="text-sm text-green-800">
                  ✅ Operation completed. Extracted: {extractedCount}, Skipped: {skippedCount}.
                  Files are in <code className="bg-green-100 px-1 rounded">extracted_files/</code>
                </p>
              </div>
            )}

            {/* Error Message */}
            {extractionStatus === 'failed' && extractionError && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm text-red-800">
                  ❌ Extraction failed: {extractionError}
                </p>
              </div>
            )}
          </div>

          <div className="flex space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open('/search?task_id=' + taskId, '_blank')}
            >
              Go to Search Page →
            </Button>
          </div>
        </div>
      </Card>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('largest')}
            className={`${activeTab === 'largest'
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Largest Files
          </button>
          <button
            onClick={() => setActiveTab('extensions')}
            className={`${activeTab === 'extensions'
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Extension Analysis
          </button>
        </nav>
      </div>

      {/* Largest Files Tab */}
      {activeTab === 'largest' && (
        <Card title={`Top ${largestFiles.length} Largest Files`}>
          {largestFiles.length === 0 ? (
            <div className="text-center py-12 text-gray-500">No files found</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Rank
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      File Path
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Size
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Extension
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {largestFiles.map((file, index) => (
                    <tr key={index} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        #{index + 1}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-900 max-w-md truncate" title={file.path || file.file_path}>
                        {file.path || file.file_path}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-mono">
                        {formatFileSize(file.size || file.file_size)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {file.extension || '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Extension Analysis Tab */}
      {activeTab === 'extensions' && extensionAnalysis && (
        <Card title="File Distribution by Extension">
          {extensionAnalysis.extension_analysis && extensionAnalysis.extension_analysis.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Extension
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Count
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Total Size
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Percentage
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {extensionAnalysis.extension_analysis
                    .sort((a, b) => (b.file_count || 0) - (a.file_count || 0))
                    .map((ext, index) => {
                      const totalCount = extensionAnalysis.total_count || extensionAnalysis.extension_analysis.reduce((sum, e) => sum + (e.file_count || 0), 0);
                      const percentage = totalCount > 0
                        ? ((ext.file_count || 0) / totalCount * 100).toFixed(1)
                        : '0.0';
                      // Debug logging
                      console.log(`Rendering extension ${index}:`, {
                        extension: ext.extension,
                        file_count: ext.file_count,
                        display_value: ext.file_count || 0,
                        typeof_file_count: typeof ext.file_count
                      });
                      return (
                        <tr key={index} className="hover:bg-gray-50">
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                              {ext.extension || '(no extension)'}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {ext.file_count || 0}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 font-mono">
                            {formatFileSize(ext.total_size || 0)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {percentage}%
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500">No extension data found</div>
          )}
        </Card>
      )}
    </div>
  );
};

export default Files;
