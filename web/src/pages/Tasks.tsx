import { useEffect, useMemo, useState } from 'react';
import { Plus, Layers } from 'lucide-react';
import { useAppDispatch, useAppSelector } from '../store';
import { fetchTasks, cancelTask, deleteTask, setFilters } from '../store/taskSlice';
import { fetchCases } from '../store/caseSlice';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useToast } from '../components/ui/Toast';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import TasksTable from '../components/tasks/TasksTable';
import CreateTaskModal from '../components/tasks/CreateTaskModal';
import AddTasksToCaseModal from '../components/tasks/AddTasksToCaseModal';
import ComposeCaseModal from '../components/tasks/ComposeCaseModal';
import { useTaskAutoTrigger } from '../hooks/useTaskAutoTrigger';
import { errorMessage } from '../lib/utils';
import type { ForensicCase } from '../types/api';

type ConfirmState =
  | { kind: 'cancel' | 'delete'; taskId: string }
  | null;

export default function Tasks() {
  const dispatch = useAppDispatch();
  const { tasks, status, filters } = useAppSelector((state) => state.tasks);
  const { cases } = useAppSelector((state) => state.cases);
  const toast = useToast();

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
        await dispatch(cancelTask({ taskId: confirm.taskId, reason: '用户取消' })).unwrap();
        toast.success('任务已取消');
      } else {
        await dispatch(deleteTask(confirm.taskId)).unwrap();
        toast.success('任务已删除');
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setConfirm(null);
    }
  };

  return (
    <div className="space-y-4 max-w-7xl">
      <Card padded={false}>
        <div className="px-5 pt-4 flex flex-wrap items-center justify-between gap-3">
          <CardHeader
            title="分析任务"
            subtitle={`共 ${tasks.length} 个任务`}
          />
          <div className="flex items-center gap-2 pb-4">
            <select
              className="select w-32 py-1.5 text-xs"
              value={filters.status}
              onChange={(e) => dispatch(setFilters({ status: e.target.value }))}
              aria-label="按状态筛选"
            >
              <option value="all">全部状态</option>
              <option value="pending">排队中</option>
              <option value="running">运行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="cancelled">已取消</option>
            </select>
            <select
              className="select w-28 py-1.5 text-xs"
              value={filters.priority}
              onChange={(e) => dispatch(setFilters({ priority: e.target.value }))}
              aria-label="按优先级筛选"
            >
              <option value="all">全部优先级</option>
              <option value="low">低</option>
              <option value="normal">普通</option>
              <option value="high">高</option>
              <option value="critical">紧急</option>
            </select>
            <Button
              size="sm"
              disabled={selectedTaskIds.size === 0}
              onClick={() => setShowCompose(true)}
            >
              <Layers size={14} /> 组建案件{selectedTaskIds.size > 0 ? `（${selectedTaskIds.size}）` : ''}
            </Button>
            <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
              <Plus size={14} /> 新建任务
            </Button>
          </div>
        </div>

        {status === 'loading' && tasks.length === 0 ? (
          <LoadingBlock text="正在加载任务…" />
        ) : tasks.length === 0 ? (
          <EmptyState
            title="暂无任务"
            description="点击「新建任务」创建第一个取证分析任务。"
            action={
              <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
                <Plus size={14} /> 新建任务
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
        title={confirm?.kind === 'cancel' ? '取消任务' : '删除任务'}
        message={
          confirm?.kind === 'cancel'
            ? '确定要取消该任务吗？正在进行的分析将被中止。'
            : '确定要删除该任务吗？任务记录及其产出数据将被移除。'
        }
        danger={confirm?.kind === 'delete'}
        confirmText={confirm?.kind === 'cancel' ? '取消任务' : '删除'}
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
