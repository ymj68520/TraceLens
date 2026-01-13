import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Link } from 'react-router-dom';
import { fetchTasks, fetchTaskStatistics } from '../store/taskSlice';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';

const Dashboard = () => {
  const dispatch = useDispatch();
  const { tasks, statistics, status } = useSelector((state) => state.tasks);

  useEffect(() => {
    dispatch(fetchTasks({ limit: 10 }));
    dispatch(fetchTaskStatistics());
  }, [dispatch]);

  const stats = React.useMemo(() => {
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
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-gray-600">
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
                <p className="text-sm font-medium text-gray-500">{stat.label}</p>
                <p className="text-2xl font-bold text-gray-900">{stat.value}</p>
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
            className="flex items-center justify-center px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <span className="mr-2">➕</span>
            Create New Task
          </Link>
          <Link
            to="/tasks"
            className="flex items-center justify-center px-4 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors"
          >
            <span className="mr-2">📋</span>
            View All Tasks
          </Link>
          <Link
            to="/search"
            className="flex items-center justify-center px-4 py-3 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 transition-colors"
          >
            <span className="mr-2">🔍</span>
            Search Files
          </Link>
        </div>
      </Card>

      {/* Recent Tasks */}
      <Card title="Recent Tasks" subtitle="Latest analysis tasks">
        {status === 'loading' ? (
          <div className="text-center py-8 text-gray-500">Loading tasks...</div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            No tasks yet. Create your first task to get started.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Task ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Image Path
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {tasks.slice(0, 5).map((task) => (
                  <tr key={task.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {task.id?.substring(0, 8)}...
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {task.progress?.overall_percentage
                        ? `${task.progress.overall_percentage.toFixed(1)}%`
                        : '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                      <Link
                        to={`/tasks`}
                        className="text-blue-600 hover:text-blue-900"
                      >
                        View Details
                      </Link>
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
            <p className="text-sm font-medium text-gray-500">Server Status</p>
            <p className="mt-1 text-sm text-gray-900 flex items-center">
              <span className="w-2 h-2 bg-green-500 rounded-full mr-2"></span>
              Online
            </p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">API Version</p>
            <p className="mt-1 text-sm text-gray-900">v1.0.0</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Backend</p>
            <p className="mt-1 text-sm text-gray-900">C++20 + Crow Framework</p>
          </div>
          <div>
            <p className="text-sm font-medium text-gray-500">Supported Formats</p>
            <p className="mt-1 text-sm text-gray-900">E01, DD, RAW</p>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default Dashboard;
