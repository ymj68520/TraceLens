import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Spinner from '../components/common/Spinner';
import {
  getMemorySummary,
  getMemoryProcesses,
  getMemoryNetwork,
  getMemoryBashHistory,
  getMemoryBootInfo,
} from '../services/memoryService';

const Memory = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks || { tasks: [] });
  const currentTask = tasks.find((t) => t.id === taskId);

  const [summary, setSummary] = useState(null);
  const [processes, setProcesses] = useState([]);
  const [network, setNetwork] = useState([]);
  const [bash, setBash] = useState([]);
  const [boot, setBoot] = useState([]);
  const [kw, setKw] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadAll = async (bashKeyword = '') => {
    if (!taskId) { setLoading(false); return; }  // else the spinner never clears
    setLoading(true);
    setError(null);
    try {
      const [s, p, n, b, bi] = await Promise.allSettled([
        getMemorySummary(taskId),
        getMemoryProcesses(taskId),
        getMemoryNetwork(taskId),
        getMemoryBashHistory(taskId, bashKeyword),
        getMemoryBootInfo(taskId),
      ]);
      if (s.status === 'fulfilled') setSummary(s.value);
      if (p.status === 'fulfilled') setProcesses(p.value || []);
      if (n.status === 'fulfilled') setNetwork(n.value || []);
      if (b.status === 'fulfilled') setBash(b.value || []);
      if (bi.status === 'fulfilled') setBoot(bi.value || []);

      const ok = [s, p, n, b, bi].some((r) => r.status === 'fulfilled' && r.value);
      if (!ok) setError('No memory data found for this task. Run with --memory-analyze first.');
    } catch (err) {
      setError(err.message || 'Failed to load memory forensics data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  const searchBash = () => loadAll(kw);

  const highlight = (cmd) => {
    if (/rm\s+-rf|zfs\s+snapshot|zfs\s+load-key|zfs\s+mount/.test(cmd)) {
      return <span className="text-red-600 dark:text-red-400 font-semibold">{cmd}</span>;
    }
    return cmd;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="p-6 space-y-6"
    >
      <div>
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">
          内存取证 Memory Forensics
        </h1>
        {currentTask && (
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Task: {currentTask.name || currentTask.id}
          </p>
        )}
      </div>

      {error && (
        <Card>
          <div className="text-red-600 dark:text-red-400">{error}</div>
        </Card>
      )}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card>
            <div className="text-xs text-slate-500 dark:text-slate-400">Processes</div>
            <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
              {summary.processes ?? 0}
            </div>
          </Card>
          <Card>
            <div className="text-xs text-slate-500 dark:text-slate-400">Network Connections</div>
            <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
              {summary.network_connections ?? 0}
            </div>
          </Card>
          <Card>
            <div className="text-xs text-slate-500 dark:text-slate-400">Bash History</div>
            <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
              {summary.bash_history ?? 0}
            </div>
          </Card>
          <Card>
            <div className="text-xs text-slate-500 dark:text-slate-400">Sockets</div>
            <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
              {summary.sockets ?? 0}
            </div>
          </Card>
        </div>
      )}

      <Card>
        <h2 className="font-semibold mb-3 text-slate-800 dark:text-slate-100">Boot Info</h2>
        <table className="w-full text-sm">
          <tbody>
            {boot.map((b, i) => (
              <tr key={i} className="border-b border-slate-100 dark:border-slate-700 last:border-0">
                <td className="py-2 font-mono text-slate-600 dark:text-slate-300">{b.key}</td>
                <td className="py-2 text-slate-800 dark:text-slate-200">{b.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card>
        <h2 className="font-semibold mb-3 text-slate-800 dark:text-slate-100">
          Processes ({processes.length})
        </h2>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-slate-800">
              <tr>
                {['PID', 'PPID', 'Comm', 'UID', 'Created'].map((h) => (
                  <th key={h} className="text-left p-2 text-slate-600 dark:text-slate-300">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {processes.map((p, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-slate-700">
                  <td className="p-2 text-slate-700 dark:text-slate-300">{p.pid}</td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">{p.ppid}</td>
                  <td className="p-2 font-mono text-slate-800 dark:text-slate-200">{p.comm}</td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">{p.uid}</td>
                  <td className="p-2 text-slate-500 dark:text-slate-400 text-xs">{p.creation_time}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold mb-3 text-slate-800 dark:text-slate-100">
          Network ({network.length})
        </h2>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-slate-800">
              <tr>
                {['PID', 'Comm', 'Proto', 'Local', 'Remote', 'State'].map((h) => (
                  <th key={h} className="text-left p-2 text-slate-600 dark:text-slate-300">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {network.map((n, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-slate-700">
                  <td className="p-2 text-slate-700 dark:text-slate-300">{n.pid}</td>
                  <td className="p-2 font-mono text-slate-800 dark:text-slate-200">{n.comm}</td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">{n.proto}</td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">
                    {n.local_addr}:{n.local_port}
                  </td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">
                    {n.remote_addr}:{n.remote_port}
                  </td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">{n.state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold mb-3 text-slate-800 dark:text-slate-100">
          Bash History ({bash.length})
        </h2>
        <div className="flex gap-2 mb-3">
          <input
            value={kw}
            onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && searchBash()}
            placeholder="filter (e.g. rm, zfs)"
            className="border border-slate-300 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100 px-3 py-1 rounded text-sm"
          />
          <button
            onClick={searchBash}
            className="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            Search
          </button>
        </div>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white dark:bg-slate-800">
              <tr>
                {['#', 'PID', 'Command'].map((h) => (
                  <th key={h} className="text-left p-2 text-slate-600 dark:text-slate-300">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bash.map((b, i) => (
                <tr key={i} className="border-b border-slate-100 dark:border-slate-700">
                  <td className="p-2 text-slate-500 dark:text-slate-400">{b.history_index}</td>
                  <td className="p-2 text-slate-700 dark:text-slate-300">{b.pid}</td>
                  <td className="p-2 font-mono text-slate-800 dark:text-slate-200">
                    {highlight(b.command)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </motion.div>
  );
};

export default Memory;
