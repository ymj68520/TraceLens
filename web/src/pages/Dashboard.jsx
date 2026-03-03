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
import { motion } from 'framer-motion';
import { ListTodo, Play, CheckCircle2, XCircle, Plus, ClipboardList, Search, Upload, Zap, Server, Database, Brain } from 'lucide-react';

const stagger = { hidden: {}, visible: { transition: { staggerChildren: 0.08 } } };
const fadeUp = { hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: { duration: 0.4 } } };

const Dashboard = () => {
  const dispatch = useDispatch();
  const { tasks, status } = useSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);

  const [systemHealth, setSystemHealth] = useState({ status: 'checking', message: 'Checking...' });
  const [depHealth, setDepHealth] = useState({
    cpp: { status: 'checking', label: 'C++ 后端', Icon: Zap, latency: null },
    python: { status: 'checking', label: 'Python 服务', Icon: Server, latency: null },
    neo4j: { status: 'checking', label: 'Neo4j 图数据库', Icon: Database, latency: null },
    llm: { status: 'checking', label: 'LLM 服务', Icon: Brain, latency: null },
  });
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    dispatch(fetchTasks({ limit: 10 }));
    dispatch(fetchTaskStatistics());
    const checkAllHealth = async () => {
      const cppStart = Date.now();
      try {
        const health = await getSystemHealth();
        setSystemHealth({ status: 'online', message: 'Online', data: health });
        setDepHealth((prev) => ({ ...prev, cpp: { ...prev.cpp, status: 'online', latency: Date.now() - cppStart } }));
      } catch {
        setSystemHealth({ status: 'offline', message: 'Offline' });
        setDepHealth((prev) => ({ ...prev, cpp: { ...prev.cpp, status: 'offline' } }));
      }
      const pyStart = Date.now();
      try {
        await getPythonHealth();
        setDepHealth((prev) => ({ ...prev, python: { ...prev.python, status: 'online', latency: Date.now() - pyStart } }));
      } catch {
        setDepHealth((prev) => ({ ...prev, python: { ...prev.python, status: 'offline' } }));
      }
      const neoStart = Date.now();
      try {
        const gStatus = await getGraphitiStatus();
        setDepHealth((prev) => ({ ...prev, neo4j: { ...prev.neo4j, status: gStatus?.neo4j_connected ? 'online' : 'offline', latency: Date.now() - neoStart } }));
      } catch {
        setDepHealth((prev) => ({ ...prev, neo4j: { ...prev.neo4j, status: 'offline' } }));
      }
      const llmStart = Date.now();
      try {
        const llmStatus = await getLLMStatus();
        setDepHealth((prev) => ({ ...prev, llm: { ...prev.llm, status: (llmStatus?.status === 'available' || llmStatus?.status === 'healthy') ? 'online' : 'offline', latency: Date.now() - llmStart } }));
      } catch {
        setDepHealth((prev) => ({ ...prev, llm: { ...prev.llm, status: 'offline' } }));
      }
    };
    checkAllHealth();
  }, [dispatch]);

  useEffect(() => {
    if (!autoRefresh) return;
    const hasRunningTasks = tasks.some((t) => t.status === 'running');
    if (!hasRunningTasks) return;
    const interval = setInterval(() => { dispatch(fetchTasks({ limit: 10 })); }, refreshInterval || 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, tasks, dispatch]);

  const stats = useMemo(() => ({
    total: tasks.length,
    running: tasks.filter((t) => t.status === 'running').length,
    completed: tasks.filter((t) => t.status === 'completed').length,
    failed: tasks.filter((t) => t.status === 'failed').length,
  }), [tasks]);

  const statCards = [
    { label: 'Total Tasks', value: stats.total, Icon: ListTodo, gradient: 'from-primary-500/20 to-primary-600/10 dark:from-primary-500/10 dark:to-primary-600/5', iconColor: 'text-primary-500' },
    { label: 'Running', value: stats.running, Icon: Play, gradient: 'from-blue-500/20 to-blue-600/10 dark:from-blue-500/10 dark:to-blue-600/5', iconColor: 'text-blue-500' },
    { label: 'Completed', value: stats.completed, Icon: CheckCircle2, gradient: 'from-emerald-500/20 to-emerald-600/10 dark:from-emerald-500/10 dark:to-emerald-600/5', iconColor: 'text-emerald-500' },
    { label: 'Failed', value: stats.failed, Icon: XCircle, gradient: 'from-rose-500/20 to-rose-600/10 dark:from-rose-500/10 dark:to-rose-600/5', iconColor: 'text-rose-500' },
  ];

  const handleToonExport = async () => {
    const completedTask = tasks.find((t) => t.status === 'completed');
    if (!completedTask) return;
    setExporting(true);
    try { await exportToon(completedTask.id); } catch { } finally { setExporting(false); }
  };

  return (
    <div className="space-y-8">
      {/* Welcome */}
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">Dashboard</h1>
        <p className="mt-1 text-slate-500 dark:text-slate-400">Welcome to the Digital Forensics Analysis Tool</p>
      </motion.div>

      {/* Statistics */}
      <motion.div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5" variants={stagger} initial="hidden" animate="visible">
        {statCards.map((stat) => {
          const Icon = stat.Icon;
          return (
            <motion.div key={stat.label} variants={fadeUp}>
              <Card className="!p-0" animate={false}>
                <div className={`flex items-center gap-4 p-5 bg-gradient-to-br ${stat.gradient} rounded-2xl`}>
                  <div className={`p-3 rounded-xl bg-white/60 dark:bg-slate-800/60 ${stat.iconColor}`}>
                    <Icon size={22} />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">{stat.label}</p>
                    <p className="text-2xl font-bold text-slate-900 dark:text-white mt-0.5">{stat.value}</p>
                  </div>
                </div>
              </Card>
            </motion.div>
          );
        })}
      </motion.div>

      {/* Health Cards */}
      <Card title="Service Health">
        <motion.div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4" variants={stagger} initial="hidden" animate="visible">
          {Object.entries(depHealth).map(([key, dep]) => {
            const Icon = dep.Icon;
            return (
              <motion.div
                key={key}
                variants={fadeUp}
                className={`p-4 rounded-xl border transition-all duration-300 ${dep.status === 'online'
                  ? 'border-emerald-500/20 bg-emerald-500/5 hover:border-emerald-500/40'
                  : dep.status === 'checking'
                    ? 'border-amber-500/20 bg-amber-500/5'
                    : 'border-rose-500/20 bg-rose-500/5'
                  }`}
              >
                <div className="flex items-center justify-between mb-3">
                  <Icon size={20} className="text-slate-500 dark:text-slate-400" />
                  <div className={`status-dot ${dep.status === 'online' ? 'status-dot-online' :
                    dep.status === 'checking' ? 'status-dot-checking' : 'status-dot-offline'
                    }`} />
                </div>
                <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{dep.label}</h4>
                <div className="flex items-center justify-between mt-1">
                  <span className={`text-xs font-medium ${dep.status === 'online' ? 'text-emerald-600 dark:text-emerald-400' :
                    dep.status === 'checking' ? 'text-amber-600' : 'text-rose-600 dark:text-rose-400'
                    }`}>
                    {dep.status === 'online' ? '在线' : dep.status === 'checking' ? '检测中...' : '离线'}
                  </span>
                  {dep.latency != null && <span className="text-xs text-slate-400 font-mono">{dep.latency}ms</span>}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      </Card>

      {/* Quick Actions */}
      <Card title="Quick Actions">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <Link to="/tasks" className="flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-xl hover:from-primary-500 hover:to-primary-400 transition-all shadow-md hover:shadow-glow-primary font-medium text-sm">
            <Plus size={16} /> Create New Task
          </Link>
          <Link to="/tasks" className="flex items-center justify-center gap-2 px-4 py-3 bg-slate-100/80 dark:bg-slate-800/60 text-slate-700 dark:text-slate-200 rounded-xl hover:bg-slate-200/80 dark:hover:bg-slate-700/60 transition-all font-medium text-sm">
            <ClipboardList size={16} /> View All Tasks
          </Link>
          <Link to="/search" className="flex items-center justify-center gap-2 px-4 py-3 bg-slate-100/80 dark:bg-slate-800/60 text-slate-700 dark:text-slate-200 rounded-xl hover:bg-slate-200/80 dark:hover:bg-slate-700/60 transition-all font-medium text-sm">
            <Search size={16} /> Search Files
          </Link>
          <button onClick={handleToonExport} disabled={exporting || !tasks.some((t) => t.status === 'completed')} className="flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-purple-600 to-purple-500 text-white rounded-xl hover:from-purple-500 hover:to-purple-400 transition-all shadow-md font-medium text-sm disabled:opacity-50 disabled:cursor-not-allowed">
            <Upload size={16} /> {exporting ? 'Exporting...' : 'TOON Export'}
          </button>
        </div>
      </Card>

      {/* Recent Tasks */}
      <Card title="Recent Tasks" subtitle="Latest analysis tasks">
        {status === 'loading' ? (
          <div className="flex items-center justify-center py-12 gap-3 text-slate-400">
            <Spinner size="md" /><span>Loading tasks...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-12 text-slate-400">No tasks yet. Create your first task to get started.</div>
        ) : (
          <div className="overflow-x-auto -mx-6">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-slate-200/50 dark:border-slate-700/30">
                  {['Task ID', 'Image Path', 'Status', 'Progress', 'Actions'].map((h) => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 5).map((task, idx) => (
                  <motion.tr
                    key={task.id}
                    className="border-b border-slate-100/50 dark:border-slate-800/30 hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors"
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.05, duration: 0.3 }}
                  >
                    <td className="px-6 py-4 text-sm font-mono text-slate-700 dark:text-slate-300">{task.id?.substring(0, 8)}...</td>
                    <td className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400 max-w-[200px] truncate">{task.image_path}</td>
                    <td className="px-6 py-4"><Badge variant={task.status === 'completed' ? 'green' : task.status === 'failed' ? 'red' : task.status === 'running' ? 'blue' : 'gray'}>{task.status}</Badge></td>
                    <td className="px-6 py-4 text-sm font-mono text-slate-500">{task.progress?.overall_percentage ? `${task.progress.overall_percentage.toFixed(1)}%` : '-'}</td>
                    <td className="px-6 py-4 text-sm font-medium space-x-3">
                      {task.status === 'completed' && (
                        <>
                          <Link to={`/timeline?task_id=${task.id}`} className="text-primary-500 hover:text-primary-400 transition-colors">Timeline</Link>
                          <Link to={`/files?task_id=${task.id}`} className="text-emerald-500 hover:text-emerald-400 transition-colors">Files</Link>
                        </>
                      )}
                      {task.status !== 'completed' && <Link to="/tasks" className="text-primary-500 hover:text-primary-400 transition-colors">View</Link>}
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* System Info */}
      <Card title="System Information">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[
            { label: 'Server Status', value: systemHealth.message, dot: systemHealth.status },
            { label: 'API Version', value: systemHealth.data?.version || 'v1.0.0' },
            { label: 'Backend', value: 'C++20 + Crow Framework' },
            { label: 'Supported Formats', value: 'E01, DD, RAW' },
          ].map((item) => (
            <div key={item.label}>
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">{item.label}</p>
              <p className="mt-1 text-sm text-slate-800 dark:text-slate-200 flex items-center gap-2">
                {item.dot && <span className={`status-dot ${item.dot === 'online' ? 'status-dot-online' : item.dot === 'checking' ? 'status-dot-checking' : 'status-dot-offline'}`} />}
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
};

export default Dashboard;
