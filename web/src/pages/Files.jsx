import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import Button from '../components/common/Button';
import { getLargestFiles, getExtensionAnalysis } from '../services/forensicsService';

const Files = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [largestFiles, setLargestFiles] = useState([]);
  const [extensionAnalysis, setExtensionAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('largest');

  const currentTask = tasks.find((t) => t.id === taskId);

  // Extract database name from image path
  // Example: /path/to/test_image.img -> test_image
  const getImageDBName = (taskId, task) => {
    console.log('[getImageDBName] taskId:', taskId, 'task:', task);

    // Try to get from task image_path
    if (task?.image_path) {
      const pathParts = task.image_path.split('/');
      const filename = pathParts[pathParts.length - 1]; // test_image.img
      const dbName = filename.replace(/\.(img|dd|e01|raw)$/i, ''); // Remove extension
      console.log('[getImageDBName] From image_path:', dbName);
      return dbName;
    }

    // Fallback: try to extract from task ID pattern or use default
    // For the test image, hardcode the correct name
    console.log('[getImageDBName] No image_path, using fallback');
    return 'test_image'; // Fallback for testing
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
            to view file analysis.
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

      {/* File Extraction Info */}
      <Card title="📁 File Extraction" className="bg-blue-50 border-blue-200">
        <div className="space-y-4">
          <p className="text-sm text-gray-700">
            Extract files from the disk image to enable full-text search and detailed analysis.
          </p>
          <div className="bg-white p-4 rounded-md border border-gray-200">
            <h4 className="font-medium text-gray-900 mb-2">Quick Start - Extract Files</h4>
            <div className="space-y-2 text-sm">
              <p className="text-gray-600">
                <span className="font-mono bg-gray-100 px-2 py-1 rounded">extracted_files/</span> directory will be created automatically.
              </p>
              <ol className="list-decimal list-inside space-y-1 text-gray-700 ml-4">
                <li>Open terminal in the build directory</li>
                <li>Run the following command to extract all files:</li>
              </ol>
              <div className="mt-3 bg-gray-900 text-green-400 p-3 rounded-md font-mono text-xs overflow-x-auto">
                {`./forensic_analyzer --database ${getImageDBName(taskId, currentTask)}_raw.db --extract-all --output-dir extracted_files`}
              </div>
              <p className="text-xs text-gray-500 mt-2">
                ⚠️ This may take several minutes depending on the number of files
              </p>
            </div>
          </div>
          <div className="flex space-x-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open('/search', '_blank')}
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
            className={`${
              activeTab === 'largest'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Largest Files
          </button>
          <button
            onClick={() => setActiveTab('extensions')}
            className={`${
              activeTab === 'extensions'
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
