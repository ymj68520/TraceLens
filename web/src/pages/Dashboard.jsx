import { useEffect, useMemo, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Link } from 'react-router-dom';
import { fetchTasks, fetchTaskStatistics } from '../store/taskSlice';
import { getSystemHealth } from '../services/systemService';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';

const Dashboard = () => {
  const dispatch = useDispatch();
  const { tasks, status } = useSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);

  // System health state
  const [systemHealth, setSystemHealth] = useState({ status: 'checking', message: 'Checking...' });

  useEffect(() => {
    dispatch(fetchTasks({ limit: 10 }));
    dispatch(fetchTaskStatistics());

    // Check system health
    const checkHealth = async () => {
      try {
        const health = await getSystemHealth();
        setSystemHealth({ status: 'online', message: 'Online', data: health });
      } catch (error) {
        setSystemHealth({ status: 'offline', message: 'Offline', error: error.message });
      }
    };

    checkHealth();
  }, [dispatch]);

  // Auto-refresh for running tasks
  useEffect(() => {
    if (!autoRefresh) return;

    const hasRunningTasks = tasks.some(t => t.status === 'running');
    if (!hasRunningTasks) return;

    const interval = setInterval(() => {
      dispatch(fetchTasks({ limit: 10 }));
    }, refreshInterval || 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, tasks, dispatch]);

  const stats = useMemo(() => {
    return {
      total: tasks.length,
      running: tasks.filter((t) => t.status === 'running').length,
      completed: tasks.filter((t) => t.status === 'completed').length,
      failed: tasks.filter((t) => t.status === 'failed').length,
    };
  }, [tasks]);

  const statCards = [
    { label: 'Total Tasks', value: stats.total, color: 'blue', icon: '📋' },
    { label: 'Running', value: stats.running, color: 'blue', icon: '▶️' },
    { label: 'Completed', value: stats.completed, color: 'green', icon: '✅' },
    { label: 'Failed', value: stats.failed, color: 'red', icon: '❌' },
  ];

  return (
    <div className="space-y-6">
      {/* Welcome Section */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">
          Welcome to the Digital Forensics Analysis Tool
        </p>
      </div>

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((stat) => (
          <Card key={stat.label} className="hover:shadow-md transition-shadow">
            <div className="flex items-center">
              <div className="text-3xl mr-4">{stat.icon}</div>
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{stat.label}</p>
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Quick Actions */}
      <Card title="Quick Actions">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Link
            to="/tasks"
            className="flex items-center justify-center px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors dark:bg-blue-500 dark:hover:bg-blue-600"
          >
            <span className="mr-2">➕</span>
            Create New Task
          </Link>
          <Link
            to="/tasks"
            className="flex items-center justify-center px-4 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
          >
            <span className="mr-2">📋</span>
            View All Tasks
          </Link>
          <Link
            to="/search"
            className="flex items-center justify-center px-4 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
          >
            <span className="mr-2">🔍</span>
            Search Files
          </Link>
        </div>
      </Card>

      {/* Recent Tasks */}
      <Card title="Recent Tasks" subtitle="Latest analysis tasks">
        {status === 'loading' ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">Loading tasks...</div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            No tasks yet. Create your first task to get started.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-800">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Task ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Image Path
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                {tasks.slice(0, 5).map((task) => (
                  <tr key={task.id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                      {task.id?.substring(0, 8)}...
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {task.image_path}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge
                        variant={
                          task.status === 'completed'
                            ? 'green'
                            : task.status === 'failed'
                              ? 'red'
                              : task.status === 'running'
                                ? 'blue'
                                : 'gray'
                        }
                      >
                        {task.status}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                      {task.progress?.overall_percentage
                        ? `${task.progress.overall_percentage.toFixed(1)}%`
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                      {task.status === 'completed' && (
                        <>
                          <Link
                            to={`/timeline?task_id=${task.id}`}
                            className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                          >
                            Timeline
                          </Link>
                          <Link
                            to={`/files?task_id=${task.id}`}
                            className="text-green-600 hover:text-green-900 dark:text-green-400 dark:hover:text-green-300"
                          >
                            Files
                          </Link>
                        </>
                      )}
                      {task.status !== 'completed' && (
                        <Link
                          to={`/tasks`}
                          className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                        >
                          View
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* System Info */}
      <Card title="System Information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Server Status</p>
            <p className="mt-1 text-sm text-gray-900 dark:text-white flex items-center">
              <span className={`w-2 h-2 rounded-full mr-2 ${systemHealth.status === 'online' ? 'bg-green-500' :
                systemHealth.status === 'checking' ? 'bg-yellow-500 animate-pulse' :
                  'bg-red-500'
                }`}></span>
              {systemHealth.message}
            </p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">API Version</p>
            <p className="mt-1 text-sm text-gray-900 dark:text-white">
              {systemHealth.data?.version || 'v1.0.0'}
            </p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Backend</p>
            <p className="mt-1 text-sm text-gray-900 dark:text-white">C++20 + Crow Framework</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Supported Formats</p>
            <p className="mt-1 text-sm text-gray-900 dark:text-white">E01, DD, RAW</p>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default Dashboard;
