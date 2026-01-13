import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import { getComprehensiveTimeline } from '../services/forensicsService';

const Timeline = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [timelineData, setTimelineData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const currentTask = tasks.find((t) => t.id === taskId);

  useEffect(() => {
    if (!taskId) {
      setError('No task ID provided. Please select a task from the Tasks page.');
      return;
    }

    const fetchTimeline = async () => {
      setLoading(true);
      setError(null);

      try {
        const data = await getComprehensiveTimeline(taskId);
        console.log('Timeline data:', data);
        console.log('First event:', data.timeline?.[0]);
        setTimelineData(data);
      } catch (err) {
        console.error('Failed to fetch timeline:', err);
        setError(err.message || 'Failed to load timeline data');
      } finally {
        setLoading(false);
      }
    };

    fetchTimeline();
  }, [taskId]);

  if (!taskId) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Timeline Analysis</h1>
          <p className="mt-2 text-gray-600">View comprehensive timeline of file system events</p>
        </div>

        <Card title="Select a Task">
          <p className="text-gray-500">
            Select a completed task from the{' '}
            <a href="/tasks" className="text-blue-600 hover:text-blue-800">
              Tasks page
            </a>{' '}
            to view timeline analysis.
          </p>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Timeline Analysis</h1>
          <p className="mt-2 text-gray-600">
            Task: {currentTask?.image_path || taskId}
          </p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-gray-600">Loading timeline data...</span>
          </div>
        </Card>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Timeline Analysis</h1>
          <p className="mt-2 text-gray-600">
            Task: {currentTask?.image_path || taskId}
          </p>
        </div>

        <Card title="Error">
          <div className="p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-red-800">{error}</p>
            <p className="text-sm text-red-600 mt-2">
              Make sure the task has completed analysis and try again.
            </p>
          </div>
        </Card>
      </div>
    );
  }

  const events = timelineData?.timeline || [];
  const totalCount = events.length;

  // Format Unix timestamp to readable date
  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '-';
    const date = new Date(timestamp * 1000); // Convert seconds to ms
    return date.toLocaleString();
  };

  // Format file size
  const formatFileSize = (bytes) => {
    if (!bytes || bytes === 0) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Timeline Analysis</h1>
        <p className="mt-2 text-gray-600">
          Task: {currentTask?.image_path || taskId}
        </p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
          </div>
        )}
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">Total Events</p>
            <p className="text-2xl font-bold text-gray-900">{totalCount}</p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">File Created</p>
            <p className="text-2xl font-bold text-green-600">
              {events.filter((e) => e.event_type === 'CREATED').length}
            </p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">File Modified</p>
            <p className="text-2xl font-bold text-blue-600">
              {events.filter((e) => e.event_type === 'MODIFIED').length}
            </p>
          </div>
        </Card>
        <Card>
          <div className="text-center">
            <p className="text-sm font-medium text-gray-500">File Deleted</p>
            <p className="text-2xl font-bold text-red-600">
              {events.filter((e) => e.event_type === 'DELETED').length}
            </p>
          </div>
        </Card>
      </div>

      {/* Timeline */}
      <Card title={`Timeline Events (${totalCount} total)`}>
        {events.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            No timeline events found for this task.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Timestamp
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    File Path
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Size
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Inode
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Description
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {events.slice(0, 100).map((event, index) => (
                  <tr key={index} className="hover:bg-gray-50">
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900 font-mono">
                      {formatTimestamp(event.timestamp)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <Badge
                        variant={
                          event.event_type === 'CREATED'
                            ? 'green'
                            : event.event_type === 'MODIFIED'
                            ? 'blue'
                            : event.event_type === 'DELETED'
                            ? 'red'
                            : 'gray'
                        }
                      >
                        {event.event_type}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-900 max-w-md truncate" title={event.file_path}>
                      {event.file_path}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                      {formatFileSize(event.file_size)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600 font-mono">
                      {event.inode || '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {event.description || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {events.length > 100 && (
              <div className="mt-4 text-center text-sm text-gray-500">
                Showing first 100 of {events.length} events
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
};

export default Timeline;
