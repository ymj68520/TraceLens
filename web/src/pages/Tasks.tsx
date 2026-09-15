import { useEffect, useMemo, useState } from 'react';
import { Plus, Layers } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks, cancelTask, deleteTask, setFilters } from '../store/taskSlice';
import { fetchCases } from '../store/caseSlice';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useToast } from '../components/ui/Toast';
import { useTranslation } from '../hooks/useTranslation';
import EmptyState from '../components/ui/EmptyState';
import { SkeletonTable } from '../components/ui/PageScaffold';
import TasksTable from '../components/tasks/TasksTable';
import CreateTaskModal from '../components/tasks/CreateTaskModal';
import AddTasksToCaseModal from '../components/tasks/AddTasksToCaseModal';
import ComposeCaseModal from '../components/tasks/ComposeCaseModal';
import { useTaskAutoTrigger } from '../hooks/useTaskAutoTrigger';
import { errorMessage } from '../lib/utils';
import { emitAppEvent } from '../lib/appEvents';
import type { ForensicCase } from '../types/api';
import { ListTodo } from 'lucide-react';
import { PageHeader } from '../components/ui/PageScaffold';

type ConfirmState =
  | { kind: 'cancel' | 'delete'; taskId: string }
  | null;

export default function Tasks() {
  const dispatch = useAppDispatch();
  const { tasks, status, filters } = useAppSelector((state) => state.tasks);
  const { cases } = useAppSelector((state) => state.cases);
  const toast = useToast();
  const { t } = useTranslation();

  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [joinTaskId, setJoinTaskId] = useState<string | null>(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set());
  const [showCompose, setShowCompose] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  useTaskAutoTrigger();

  useEffect(() => {
    void dispatch(fetchTasks(filters));
    void dispatch(fetchCases());
  }, [dispatch, filters]);

  const taskCaseMap = useMemo(() => {
    const m: Record<string, ForensicCase> = {};
    for (const c of cases || []) {
      for (const tid of c.task_ids || []) m[tid] = c;
    }
    return m;
  }, [cases]);

  const toggleSelect = (taskId: string) =>
    setSelectedTaskIds((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });

  const toggleSelectAll = (checked: boolean) => {
    if (!checked) {
      setSelectedTaskIds(new Set());
      return;
    }
    setSelectedTaskIds(
      new Set(tasks.filter((t) => t.status?.toLowerCase() === 'completed').map((t) => t.id)),
    );
  };

  const handleConfirm = async () => {
    if (!confirm) return;
    try {
      if (confirm.kind === 'cancel') {
        await dispatch(cancelTask({ taskId: confirm.taskId, reason: t('tasks.cancel_reason') })).unwrap();
        toast.success(t('tasks.toast.cancelled'));
        emitAppEvent({ kind: 'info', title: t('tasks.toast.cancelled'), detail: confirm.taskId });
      } else {
        await dispatch(deleteTask(confirm.taskId)).unwrap();
        toast.success(t('tasks.toast.deleted'));
        emitAppEvent({ kind: 'success', title: t('tasks.toast.deleted'), detail: confirm.taskId });
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setConfirm(null);
    }
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <PageHeader icon={ListTodo} tone="accent" title={t('nav.tasks')} subtitle={t('tasks.subtitle')} />
      <Card padded={false}>
        <div className="px-5 pt-4 flex flex-wrap items-center justify-between gap-3">
          <CardHeader
            title={t('tasks.title')}
            subtitle={t('tasks.count').replace('{n}', String(tasks.length))}
          />
          <div className="flex items-center gap-2 pb-4">
            <select
              className="select w-32 py-1.5 text-xs"
              value={filters.status}
              onChange={(e) => dispatch(setFilters({ status: e.target.value }))}
              aria-label={t('tasks.filter.status_aria')}
            >
              <option value="all">{t('tasks.filter.all_status')}</option>
              <option value="pending">{t('task.status.pending')}</option>
              <option value="running">{t('task.status.running')}</option>
              <option value="completed">{t('task.status.completed')}</option>
              <option value="failed">{t('task.status.failed')}</option>
              <option value="cancelled">{t('task.status.cancelled')}</option>
            </select>
            <select
              className="select w-28 py-1.5 text-xs"
              value={filters.priority}
              onChange={(e) => dispatch(setFilters({ priority: e.target.value }))}
              aria-label={t('tasks.filter.priority_aria')}
            >
              <option value="all">{t('tasks.filter.all_priority')}</option>
              <option value="low">{t('task.priority.low')}</option>
              <option value="normal">{t('task.priority.normal')}</option>
              <option value="high">{t('task.priority.high')}</option>
              <option value="critical">{t('task.priority.critical')}</option>
            </select>
            <Button
              size="sm"
              disabled={selectedTaskIds.size === 0}
              onClick={() => setShowCompose(true)}
            >
              <Layers size={14} /> {selectedTaskIds.size > 0 ? t('tasks.compose_count').replace('{n}', String(selectedTaskIds.size)) : t('tasks.compose')}
            </Button>
            <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
              <Plus size={14} /> {t('tasks.new')}
            </Button>
          </div>
        </div>

        {status === 'loading' && tasks.length === 0 ? (
          <SkeletonTable rows={6} cols={5} />
        ) : tasks.length === 0 ? (
          <EmptyState
            title={t('tasks.empty.title')}
            description={t('tasks.empty.desc')}
            action={
              <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
                <Plus size={14} /> {t('tasks.new')}
              </Button>
            }
          />
        ) : (
          <TasksTable
            tasks={tasks}
            taskCaseMap={taskCaseMap}
            selectedIds={selectedTaskIds}
            onToggleSelect={toggleSelect}
            onToggleSelectAll={toggleSelectAll}
            onCancel={(taskId) => setConfirm({ kind: 'cancel', taskId })}
            onDelete={(taskId) => setConfirm({ kind: 'delete', taskId })}
            onJoinCase={(taskId) => setJoinTaskId(taskId)}
          />
        )}
      </Card>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.kind === 'cancel' ? t('tasks.confirm.cancel_title') : t('tasks.confirm.delete_title')}
        message={
          confirm?.kind === 'cancel'
            ? t('tasks.confirm.cancel_message')
            : t('tasks.confirm.delete_message')
        }
        danger={confirm?.kind === 'delete'}
        confirmText={confirm?.kind === 'cancel' ? t('tasks.confirm.cancel_confirm') : t('tasks.confirm.delete_confirm')}
        onConfirm={handleConfirm}
        onCancel={() => setConfirm(null)}
      />

      <CreateTaskModal open={showCreate} onClose={() => setShowCreate(false)} />

      {joinTaskId && (
        <AddTasksToCaseModal fixedTaskId={joinTaskId} onClose={() => setJoinTaskId(null)} />
      )}

      {showCompose && (
        <ComposeCaseModal
          preselectedTaskIds={[...selectedTaskIds]}
          onClose={() => {
            setShowCompose(false);
            setSelectedTaskIds(new Set());
          }}
        />
      )}
    </div>
  );
}
