import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ListTodo,
  Play,
  CheckCircle2,
  XCircle,
  Plus,
  ClipboardList,
  Search,
  Upload,
  type LucideIcon,
} from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks, fetchTaskStatistics } from '../store/taskSlice';
import { exportToon } from '../services/systemService';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import { LoadingBlock } from '../components/ui/Spinner';
import EmptyState from '../components/ui/EmptyState';
import ServiceHealthStrip from './dashboard/components/ServiceHealthStrip';
import { basename } from '../lib/utils';

interface StatCardSpec {
  label: string;
  value: number;
  Icon: LucideIcon;
  iconClass: string;
}

const STATUS_TONE: Record<string, 'success' | 'danger' | 'accent' | 'neutral' | 'warning'> = {
  completed: 'success',
  failed: 'danger',
  running: 'accent',
  pending: 'warning',
  cancelled: 'neutral',
};

export default function Dashboard() {
  const dispatch = useAppDispatch();
  const { tasks, status } = useAppSelector((state) => state.tasks);
  const { autoRefresh, refreshInterval } = useAppSelector((state) => state.settings);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    void dispatch(fetchTasks({ limit: 10 }));
    void dispatch(fetchTaskStatistics());
  }, [dispatch]);

  useEffect(() => {
    if (!autoRefresh) return;
    if (!tasks.some((t) => t.status === 'running')) return;
    const id = setInterval(() => {
      void dispatch(fetchTasks({ limit: 10 }));
    }, refreshInterval || 5000);
    return () => clearInterval(id);
  }, [autoRefresh, refreshInterval, tasks, dispatch]);

  const stats = useMemo(
    () => ({
      total: tasks.length,
      running: tasks.filter((t) => t.status === 'running').length,
      completed: tasks.filter((t) => t.status === 'completed').length,
      failed: tasks.filter((t) => t.status === 'failed').length,
    }),
    [tasks],
  );

  const statCards: StatCardSpec[] = [
    { label: '任务总数', value: stats.total, Icon: ListTodo, iconClass: 'text-accent-600 bg-accent-50 dark:bg-accent-500/10' },
    { label: '运行中', value: stats.running, Icon: Play, iconClass: 'text-sky-600 bg-sky-50 dark:bg-sky-500/10' },
    { label: '已完成', value: stats.completed, Icon: CheckCircle2, iconClass: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-500/10' },
    { label: '失败', value: stats.failed, Icon: XCircle, iconClass: 'text-rose-600 bg-rose-50 dark:bg-rose-500/10' },
  ];

  const handleToonExport = async () => {
    const completedTask = tasks.find((t) => t.status === 'completed');
    if (!completedTask) return;
    setExporting(true);
    try {
      await exportToon(completedTask.id);
    } catch {
      // best effort
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map(({ label, value, Icon, iconClass }) => (
          <Card key={label} hover className="flex items-center gap-3.5">
            <div className={`p-2.5 rounded-md ${iconClass}`}>
              <Icon size={20} />
            </div>
            <div>
              <p className="text-2xs font-medium text-ink-500 dark:text-ink-400 uppercase tracking-wide">
                {label}
              </p>
              <p className="text-2xl font-bold text-ink-900 dark:text-white mt-0.5 tabular-nums">
                {value}
              </p>
            </div>
          </Card>
        ))}
      </div>

      <ServiceHealthStrip />

      {/* Quick actions */}
      <Card padded={false} className="p-4">
        <div className="flex flex-wrap gap-2.5">
          <Link to="/tasks" className="btn-primary">
            <Plus size={15} /> 新建任务
          </Link>
          <Link to="/tasks" className="btn-secondary">
            <ClipboardList size={15} /> 任务列表
          </Link>
          <Link to="/search" className="btn-secondary">
            <Search size={15} /> 全文搜索
          </Link>
          <button
            type="button"
            onClick={handleToonExport}
            disabled={exporting || !tasks.some((t) => t.status === 'completed')}
            className="btn-secondary"
          >
            <Upload size={15} /> {exporting ? '导出中…' : 'TOON 导出'}
          </button>
        </div>
      </Card>

      {/* Recent tasks */}
      <Card padded={false}>
        <div className="px-5 pt-4">
          <CardHeader title="最近任务" subtitle="最新创建的分析任务" />
        </div>
        {status === 'loading' ? (
          <LoadingBlock text="正在加载任务…" />
        ) : tasks.length === 0 ? (
          <EmptyState
            title="还没有任务"
            description="创建第一个取证分析任务以开始工作。"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-shell">
              <thead>
                <tr>
                  <th>任务 ID</th>
                  <th>镜像路径</th>
                  <th>状态</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 6).map((task) => (
                  <tr key={task.id}>
                    <td className="font-mono text-xs">{task.id.substring(0, 8)}…</td>
                    <td className="max-w-[280px] truncate" title={task.image_path}>
                      {basename(task.image_path)}
                    </td>
                    <td>
                      <Badge tone={STATUS_TONE[task.status] ?? 'neutral'}>{task.status}</Badge>
                    </td>
                    <td className="text-right text-xs">
                      {task.status === 'completed' ? (
                        <span className="space-x-3">
                          <Link
                            to={`/timeline?task_id=${task.id}`}
                            className="text-accent-600 dark:text-accent-400 hover:underline"
                          >
                            时间线
                          </Link>
                          <Link
                            to={`/files?task_id=${task.id}`}
                            className="text-accent-600 dark:text-accent-400 hover:underline"
                          >
                            文件
                          </Link>
                        </span>
                      ) : (
                        <Link to="/tasks" className="text-accent-600 dark:text-accent-400 hover:underline">
                          查看
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
    </div>
  );
}
