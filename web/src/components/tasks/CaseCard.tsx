import { Briefcase, Play, Plus, Trash2, FolderPlus, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { ForensicCase, ForensicTask } from '../../types/api';
import Badge from '../ui/Badge';
import ProgressBar from '../ui/ProgressBar';
import Button from '../ui/Button';
import { formatDateTime, basename } from '../../lib/utils';

export interface CasePollingState {
  jobId: string;
  stage: string;
  message: string;
}

const STATUS_TONE: Record<string, 'info' | 'warning' | 'success' | 'danger' | 'neutral'> = {
  open: 'info',
  analysing: 'warning',
  completed: 'success',
  failed: 'danger',
};

const STATUS_LABEL: Record<string, string> = {
  open: '待分析',
  analysing: '分析中',
  completed: '已完成',
  failed: '失败',
};

interface CaseCardProps {
  forensicCase: ForensicCase;
  tasks: ForensicTask[];
  polling?: CasePollingState;
  onStartAnalysis: (c: ForensicCase) => void;
  onAddTasks: (caseId: string) => void;
  onDelete: (c: ForensicCase) => void;
}

export default function CaseCard({
  forensicCase: c,
  tasks,
  polling,
  onStartAnalysis,
  onAddTasks,
  onDelete,
}: CaseCardProps) {
  const caseTasks = (c.task_ids || [])
    .map((id) => tasks.find((t) => t.id === id))
    .filter((t): t is ForensicTask => Boolean(t));

  const completed = caseTasks.filter((t) => t.status === 'completed').length;
  const running = caseTasks.filter((t) => t.status === 'running').length;
  const total = caseTasks.length;
  const allDone = total > 0 && completed === total;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div className="card card-pad card-hover flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-2 rounded-md bg-accent-50 dark:bg-accent-500/10 text-accent-600 dark:text-accent-400 shrink-0">
            <Briefcase size={17} />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-100 truncate">{c.name}</h3>
            <p className="text-2xs font-mono text-ink-400">{c.id.substring(0, 8)}…</p>
          </div>
        </div>
        <Badge tone={STATUS_TONE[c.status ?? 'open'] ?? 'neutral'}>
          {STATUS_LABEL[c.status ?? 'open'] ?? c.status}
        </Badge>
      </div>

      {c.description && (
        <p className="text-xs text-ink-500 dark:text-ink-400 line-clamp-2 leading-relaxed">
          {c.description}
        </p>
      )}

      <div>
        <div className="flex items-center justify-between text-2xs text-ink-500 mb-1">
          <span>
            {completed}/{total} 任务完成{running > 0 ? `，${running} 运行中` : ''}
          </span>
          <span className="font-mono">{pct}%</span>
        </div>
        <ProgressBar value={pct} />
      </div>

      {polling && (
        <div className="text-xs bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/20 rounded-md px-3 py-2 text-accent-700 dark:text-accent-300">
          <span className="font-medium">{polling.stage}</span>
          {polling.message && <span className="ml-1.5 text-accent-600/80">{polling.message}</span>}
        </div>
      )}

      {caseTasks.length > 0 && (
        <ul className="text-2xs text-ink-500 dark:text-ink-400 space-y-0.5 max-h-20 overflow-y-auto">
          {caseTasks.map((t) => (
            <li key={t.id} className="flex items-center gap-1.5 truncate">
              <span
                className={
                  t.status === 'completed'
                    ? 'dot-ok'
                    : t.status === 'running'
                      ? 'dot-run'
                      : t.status === 'failed'
                        ? 'dot-err'
                        : 'dot-idle'
                }
              />
              <span className="truncate">{basename(t.image_path)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center gap-1.5 pt-1 border-t border-ink-100 dark:border-ink-800 mt-auto flex-wrap">
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
        <Button size="sm" onClick={() => onAddTasks(c.id)}>
          <FolderPlus size={13} /> 关联任务
        </Button>
        <Button size="sm" variant="ghost" className="ml-auto text-rose-600" onClick={() => onDelete(c)}>
          <Trash2 size={13} />
        </Button>
      </div>

      <p className="text-2xs text-ink-400">创建于 {formatDateTime(c.created_at)}</p>
    </div>
  );
}

export function CaseCreateButton({ onClick, onCompose }: { onClick: () => void; onCompose: () => void }) {
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" onClick={onCompose}>
        从已有任务组建
      </Button>
      <Button variant="primary" size="sm" onClick={onClick}>
        <Plus size={14} /> 新建案件
      </Button>
    </div>
  );
}
