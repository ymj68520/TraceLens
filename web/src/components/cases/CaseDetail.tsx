import { useMemo, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Briefcase,
  CalendarDays,
  Download,
  ExternalLink,
  FileClock,
  FolderOpen,
  FolderPlus,
  Hash,
  Layers,
  Play,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
import type { ForensicCase, ForensicTask } from '../../types/api';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import ProgressBar from '../ui/ProgressBar';
import EmptyState from '../ui/EmptyState';
import { useToast } from '../ui/Toast';
import { useTranslation } from '../../hooks/useTranslation';
import { basename, formatDateTime, getTaskCreatedMs } from '../../lib/utils';
import { downloadJSON } from '../../lib/exportUtils';
import { buildCaseArchive, caseStatusLabel, caseStatusTone, getTaskProgress } from './caseUtils';
import type { CasePollingState } from '../tasks/CaseCard';

/* Task-status pill tone, mirrors TasksTable. */
const TASK_STATUS_TONE: Record<string, 'success' | 'danger' | 'accent' | 'neutral' | 'warning'> = {
  completed: 'success',
  failed: 'danger',
  running: 'accent',
  pending: 'warning',
  cancelled: 'neutral',
};

interface CaseDetailProps {
  forensicCase: ForensicCase;
  tasks: ForensicTask[];
  polling?: CasePollingState;
  onBack: () => void;
  onStartAnalysis: (c: ForensicCase) => void;
  onAddTasks: (caseId: string) => void;
  onDelete: (c: ForensicCase) => void;
}

/**
 * Full-page case detail: header card with metadata and aggregate actions,
 * then the associated-task table. Rendered by Cases when ?case=<id> is set.
 */
export default function CaseDetail({
  forensicCase: c,
  tasks,
  polling,
  onBack,
  onStartAnalysis,
  onAddTasks,
  onDelete,
}: CaseDetailProps) {
  const toast = useToast();
  const { t } = useTranslation();

  const caseTasks = useMemo(
    () =>
      (c.task_ids ?? [])
        .map((id) => tasks.find((task) => task.id === id))
        .filter((task): task is ForensicTask => Boolean(task)),
    [c.task_ids, tasks],
  );
  const totalIds = (c.task_ids ?? []).length;
  const missingCount = totalIds - caseTasks.length;

  const completed = caseTasks.filter((task) => task.status === 'completed').length;
  const total = caseTasks.length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const allDone = total > 0 && completed === total;
  const firstTask = caseTasks[0];

  const handleExport = () => {
    downloadJSON(buildCaseArchive(c, caseTasks), `case-${c.id.slice(0, 8)}-archive`);
    toast.success(`案件「${c.name}」档案已导出`);
  };

  const linkCls =
    'text-2xs text-accent-600 dark:text-accent-400 hover:underline inline-flex items-center gap-1 whitespace-nowrap';

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1 text-xs text-ink-500 dark:text-ink-400 hover:text-accent-600 dark:hover:text-accent-400 transition-colors"
      >
        <ArrowLeft size={13} /> 返回案件列表
      </button>

      {/* ------------------------------ Header ------------------------------ */}
      <div className="card card-pad">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div className="p-2.5 rounded-lg bg-accent-50 dark:bg-accent-500/10 text-accent-600 dark:text-accent-400 shrink-0">
              <Briefcase size={20} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-semibold text-ink-900 dark:text-ink-100 truncate">
                  {c.name}
                </h2>
                <Badge tone={caseStatusTone(c.status)} dot>
                  {caseStatusLabel(c.status)}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-ink-500 dark:text-ink-400 leading-relaxed max-w-2xl">
                {c.description || '暂无案件描述'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            {allDone && c.status !== 'completed' && !polling && (
              <Button variant="primary" size="sm" onClick={() => onStartAnalysis(c)}>
                <Play size={13} /> 跨镜像分析
              </Button>
            )}
            {c.status === 'completed' && (
              <Link to={`/case-intelligence?case_id=${c.id}`} className="btn-primary btn-sm">
                <ExternalLink size={13} /> 查看报告
              </Link>
            )}
            {firstTask ? (
              <Link to={`/timeline?task_id=${firstTask.id}`} className="btn-secondary btn-sm" title={`打开任务 ${firstTask.id} 的时间线`}>
                <FileClock size={13} /> 时间线
              </Link>
            ) : (
              <Button size="sm" disabled title="案件暂无关联任务">
                <FileClock size={13} /> 时间线
              </Button>
            )}
            <Button size="sm" onClick={handleExport}>
              <Download size={13} /> 导出档案
            </Button>
            <Button size="sm" onClick={() => onAddTasks(c.id)}>
              <FolderPlus size={13} /> 关联任务
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-rose-600 dark:text-rose-400"
              onClick={() => onDelete(c)}
            >
              <Trash2 size={13} /> 删除
            </Button>
          </div>
        </div>

        {polling && (
          <div className="mt-3 text-xs bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/20 rounded-md px-3 py-2 text-accent-700 dark:text-accent-300">
            <span className="font-medium">{polling.stage}</span>
            {polling.message && <span className="ml-1.5 text-accent-600/80">{polling.message}</span>}
          </div>
        )}

        {/* Metadata grid */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 pt-3 border-t border-ink-100 dark:border-ink-800">
          <MetaItem icon={Hash} label="案件 ID">
            <span className="font-mono break-all">{c.id}</span>
          </MetaItem>
          <MetaItem icon={CalendarDays} label="创建时间">
            {formatDateTime(c.created_at)}
          </MetaItem>
          <MetaItem icon={Layers} label="任务规模">
            共 {totalIds} 个任务，{completed} 个已完成
            {missingCount > 0 && <span className="text-ink-400">（{missingCount} 个详情不可用）</span>}
          </MetaItem>
        </div>

        <div className="mt-4">
          <div className="flex items-center justify-between text-2xs text-ink-500 dark:text-ink-400 mb-1.5">
            <span>任务完成进度</span>
            <span className="font-mono">{pct}%</span>
          </div>
          <ProgressBar value={pct} />
        </div>
      </div>

      {/* --------------------------- Task table ---------------------------- */}
      <div className="card">
        <div className="px-5 pt-4 pb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="card-title">关联任务清单</h3>
            <p className="card-subtitle mt-0.5">
              共 {totalIds} 个任务{missingCount > 0 ? `，${missingCount} 个详情不可用` : ''}
            </p>
          </div>
          <Button size="sm" onClick={() => onAddTasks(c.id)}>
            <FolderPlus size={13} /> 关联任务
          </Button>
        </div>

        {caseTasks.length === 0 ? (
          <EmptyState
            className="py-10"
            icon={<FolderPlus size={30} />}
            title="暂无关联任务"
            description="将已完成的取证任务关联到该案件，即可进行跨镜像关联分析。"
            action={
              <Button variant="primary" size="sm" onClick={() => onAddTasks(c.id)}>
                <FolderPlus size={14} /> 关联任务
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-shell">
              <thead>
                <tr>
                  <th>任务 ID</th>
                  <th>镜像</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>创建时间</th>
                  <th className="text-right">快捷入口</th>
                </tr>
              </thead>
              <tbody>
                {caseTasks.map((task) => {
                  const status = (task.status || '').toLowerCase();
                  return (
                    <tr key={task.id}>
                      <td>
                        <span
                          className="font-mono text-2xs text-ink-500 dark:text-ink-400"
                          title={task.id}
                        >
                          {task.id.slice(0, 8)}…
                        </span>
                      </td>
                      <td>
                        <p
                          className="text-xs font-medium text-ink-900 dark:text-ink-100 truncate max-w-[240px]"
                          title={task.image_path}
                        >
                          {basename(task.image_path) || task.image_path}
                        </p>
                      </td>
                      <td>
                        <Badge tone={TASK_STATUS_TONE[status] ?? 'neutral'} dot>
                          {t(`task.status.${status}`)}
                        </Badge>
                      </td>
                      <td className="w-36">
                        <ProgressBar value={getTaskProgress(task)} showLabel />
                      </td>
                      <td className="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap">
                        {formatDateTime(getTaskCreatedMs(task))}
                      </td>
                      <td>
                        <div className="flex items-center justify-end gap-3">
                          <Link to={`/timeline?task_id=${task.id}`} className={linkCls}>
                            <FileClock size={12} /> 时间线
                          </Link>
                          <Link to={`/files?task_id=${task.id}`} className={linkCls}>
                            <FolderOpen size={12} /> 文件
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function MetaItem({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <p className="section-label flex items-center gap-1">
        <Icon size={11} aria-hidden /> {label}
      </p>
      <div className="mt-1 text-xs text-ink-800 dark:text-ink-200">{children}</div>
    </div>
  );
}
