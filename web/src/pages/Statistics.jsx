import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import { getStatisticsOverview } from '../services/forensicsService';

const Statistics = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [statistics, setStatistics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const currentTask = tasks.find((t) => t.id === taskId);

  useEffect(() => {
    if (!taskId) {
      setError('No task ID provided. Please select a task from the Tasks page.');
      return;
    }

    const fetchStatistics = async () => {
      setLoading(true);
      setError(null);

      try {
        const data = await getStatisticsOverview(taskId);
        console.log('Statistics data:', data);
        console.log('Raw stats:', data?.raw_database_stats?.[0]);
        console.log('Files stats:', data?.files_database_stats?.[0]);
        console.log('Events stats:', data?.events_database_stats?.[0]);
        setStatistics(data);
      } catch (err) {
        console.error('Failed to fetch statistics:', err);
        // Set empty statistics object on error to prevent page crash
        setStatistics({ overview: {} });
        setError(err.message || 'Failed to load statistics');
      } finally {
        setLoading(false);
      }
    };

    fetchStatistics();
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
          <h1 className="text-3xl font-bold text-gray-900">Statistics</h1>
          <p className="mt-2 text-gray-600">Comprehensive analysis statistics and reports</p>
        </div>

        <Card title="Select a Task">
          <p className="text-gray-500">
            Select a completed task from the{' '}
            <a href="/tasks" className="text-blue-600 hover:text-blue-800">
              Tasks page
            </a>{' '}
            to view statistics.
          </p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Statistics</h1>
          <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-gray-600">Loading statistics...</span>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Statistics</h1>
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

  // Extract statistics from response
  const rawStats = statistics?.raw_database_stats?.[0] || {};
  const filesStats = statistics?.files_database_stats?.[0] || {};
  const eventsStats = statistics?.events_database_stats?.[0] || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Statistics</h1>
        <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
          </div>
        )}
      </div>

      {/* Overview Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">Total Files</p>
            <p className="text-3xl font-bold text-gray-900 mt-2">
              {rawStats.total_files || 0}
            </p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">Total Size</p>
            <p className="text-3xl font-bold text-gray-900 mt-2">
              {formatFileSize(rawStats.total_size || 0)}
            </p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">Categorized Files</p>
            <p className="text-3xl font-bold text-blue-900 mt-2">
              {filesStats.categorized_files || 0}
            </p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">Deleted Files</p>
            <p className="text-3xl font-bold text-red-600 mt-2">
              {rawStats.deleted_files || 0}
            </p>
          </div>
        </Card>
      </div>

      {/* Database Statistics */}
      <Card title="Database Statistics">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-4 bg-blue-50 rounded-lg">
            <p className="text-sm font-medium text-blue-800">Raw Database</p>
            <p className="text-2xl font-bold text-blue-900 mt-2">
              {rawStats.total_files || 0} files
            </p>
            <p className="text-sm text-blue-700 mt-1">
              {formatFileSize(rawStats.total_size || 0)}
            </p>
          </div>
          <div className="p-4 bg-green-50 rounded-lg">
            <p className="text-sm font-medium text-green-800">Files Database</p>
            <p className="text-2xl font-bold text-green-900 mt-2">
              {filesStats.categorized_files || 0} files
            </p>
            <p className="text-sm text-green-700 mt-1">
              {filesStats.categories || 0} categories
            </p>
          </div>
          <div className="p-4 bg-purple-50 rounded-lg">
            <p className="text-sm font-medium text-purple-800">Events Database</p>
            <p className="text-2xl font-bold text-purple-900 mt-2">
              {eventsStats.total_events || 0} events
            </p>
            <p className="text-sm text-purple-700 mt-1">
              {eventsStats.unique_files_affected || 0} files
            </p>
          </div>
        </div>
      </Card>

      {/* Timeline Statistics */}
      {eventsStats && (
        <Card title="Timeline Activity">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-sm font-medium text-gray-600">Event Types</p>
              <p className="text-2xl font-bold text-gray-900 mt-2">
                {eventsStats.event_types || 0}
              </p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-sm font-medium text-gray-600">Unique Files Affected</p>
              <p className="text-2xl font-bold text-gray-900 mt-2">
                {eventsStats.unique_files_affected || 0}
              </p>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
};

export default Statistics;
