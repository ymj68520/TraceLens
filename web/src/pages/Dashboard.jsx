import { useEffect, useMemo, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Link } from 'react-router-dom';
import { fetchTasks, fetchTaskStatistics } from '../store/taskSlice';
import { getSystemHealth, getPythonHealth, exportToon } from '../services/systemService';
import { getLLMStatus } from '../services/llmService';
import { getGraphitiStatus } from '../services/graphitiService';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';

const Dashboard = () => {
  const dispatch = useDispatch();
  const { tasks, status } = useSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);

  // System health state
  const [systemHealth, setSystemHealth] = useState({ status: 'checking', message: 'Checking...' });

  // Dependency health states
  const [depHealth, setDepHealth] = useState({
    cpp: { status: 'checking', label: 'C++ 后端', icon: '⚡', latency: null },
    python: { status: 'checking', label: 'Python 服务', icon: '🐍', latency: null },
    neo4j: { status: 'checking', label: 'Neo4j 图数据库', icon: '🕸️', latency: null },
    llm: { status: 'checking', label: 'LLM 服务', icon: '🧠', latency: null },
  });

  // TOON export state
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    dispatch(fetchTasks({ limit: 10 }));
    dispatch(fetchTaskStatistics());

    // Check all service health in parallel
    const checkAllHealth = async () => {
      // C++ backend
      const cppStart = Date.now();
      try {
        const health = await getSystemHealth();
        setSystemHealth({ status: 'online', message: 'Online', data: health });
        setDepHealth((prev) => ({ ...prev, cpp: { ...prev.cpp, status: 'online', latency: Date.now() - cppStart } }));
      } catch {
        setSystemHealth({ status: 'offline', message: 'Offline' });
        setDepHealth((prev) => ({ ...prev, cpp: { ...prev.cpp, status: 'offline' } }));
      }

      // Python service
      const pyStart = Date.now();
      try {
        await getPythonHealth();
        setDepHealth((prev) => ({ ...prev, python: { ...prev.python, status: 'online', latency: Date.now() - pyStart } }));
      } catch {
        setDepHealth((prev) => ({ ...prev, python: { ...prev.python, status: 'offline' } }));
      }

      // Neo4j (via Graphiti status)
      const neoStart = Date.now();
      try {
        const gStatus = await getGraphitiStatus();
        setDepHealth((prev) => ({
          ...prev,
          neo4j: { ...prev.neo4j, status: gStatus?.neo4j_connected ? 'online' : 'offline', latency: Date.now() - neoStart },
        }));
      } catch {
        setDepHealth((prev) => ({ ...prev, neo4j: { ...prev.neo4j, status: 'offline' } }));
      }

      // LLM
      const llmStart = Date.now();
      try {
        const llmStatus = await getLLMStatus();
        setDepHealth((prev) => ({
          ...prev,
          llm: { ...prev.llm, status: llmStatus?.status === 'healthy' ? 'online' : 'offline', latency: Date.now() - llmStart },
        }));
      } catch {
        setDepHealth((prev) => ({ ...prev, llm: { ...prev.llm, status: 'offline' } }));
      }
    };

    checkAllHealth();
  }, [dispatch]);

  // Auto-refresh for running tasks
  useEffect(() => {
    if (!autoRefresh) return;
    const hasRunningTasks = tasks.some((t) => t.status === 'running');
    if (!hasRunningTasks) return;
    const interval = setInterval(() => {
      dispatch(fetchTasks({ limit: 10 }));
    }, refreshInterval || 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, tasks, dispatch]);

  const stats = useMemo(() => ({
    total: tasks.length,
    running: tasks.filter((t) => t.status === 'running').length,
    completed: tasks.filter((t) => t.status === 'completed').length,
    failed: tasks.filter((t) => t.status === 'failed').length,
  }), [tasks]);

  const statCards = [
    { label: 'Total Tasks', value: stats.total, color: 'blue', icon: '📋' },
    { label: 'Running', value: stats.running, color: 'blue', icon: '▶️' },
    { label: 'Completed', value: stats.completed, color: 'green', icon: '✅' },
    { label: 'Failed', value: stats.failed, color: 'red', icon: '❌' },
  ];

  const handleToonExport = async () => {
    const completedTask = tasks.find((t) => t.status === 'completed');
    if (!completedTask) return;
    setExporting(true);
    try {
      await exportToon(completedTask.id);
    } catch {
      // Silently handle — toast would be ideal here
    } finally {
      setExporting(false);
    }
  };

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

      {/* Dependency Health Cards */}
      <Card title="🏥 服务依赖状态">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Object.entries(depHealth).map(([key, dep]) => (
            <div
              key={key}
              className={`p-4 rounded-lg border transition-shadow hover:shadow-md ${dep.status === 'online'
                  ? 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/20'
                  : dep.status === 'checking'
                    ? 'border-yellow-200 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-900/20'
                    : 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20'
                }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-2xl">{dep.icon}</span>
                <span
                  className={`w-3 h-3 rounded-full ${dep.status === 'online'
                      ? 'bg-green-500'
                      : dep.status === 'checking'
                        ? 'bg-yellow-500 animate-pulse'
                        : 'bg-red-500'
                    }`}
                />
              </div>
              <h4 className="text-sm font-medium text-gray-900 dark:text-white">{dep.label}</h4>
              <div className="flex items-center justify-between mt-1">
                <span className={`text-xs font-medium ${dep.status === 'online' ? 'text-green-600 dark:text-green-400' :
                    dep.status === 'checking' ? 'text-yellow-600' : 'text-red-600 dark:text-red-400'
                  }`}>
                  {dep.status === 'online' ? '在线' : dep.status === 'checking' ? '检测中...' : '离线'}
                </span>
                {dep.latency != null && (
                  <span className="text-xs text-gray-400">{dep.latency}ms</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Quick Actions */}
      <Card title="Quick Actions">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
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
          <button
            onClick={handleToonExport}
            disabled={exporting || !tasks.some((t) => t.status === 'completed')}
            className="flex items-center justify-center px-4 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="mr-2">📤</span>
            {exporting ? 'Exporting...' : 'TOON Export'}
          </button>
        </div>
      </Card>

      {/* Recent Tasks */}
      <Card title="Recent Tasks" subtitle="Latest analysis tasks">
        {status === 'loading' ? (
          <div className="text-center py-8 text-gray-500 dark:text-gray-400">
            <Spinner size="md" />
            <span className="ml-2">Loading tasks...</span>
          </div>
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

