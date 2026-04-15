import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { fetchTasks, cancelTask, deleteTask, setFilters } from '../store/taskSlice';
import { openModal } from '../store/uiSlice';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Spinner from '../components/common/Spinner';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/ToastContext';
import { TASK_STATUS, TASK_PRIORITY } from '../utils/constants';
import TaskTable from '../components/tasks/TaskTable';
import CreateTaskModal from '../components/tasks/CreateTaskModal';
import { useTaskAutoTrigger } from '../hooks/useTaskAutoTrigger';

const Tasks = () => {
  const dispatch = useDispatch();
  const { tasks, status, error, filters } = useSelector((state) => state.tasks);
  const { modal } = useSelector((state) => state.ui);
  const toast = useToast();

  // Confirmation dialog state
  const [confirmState, setConfirmState] = useState({ open: false, type: null, taskId: null, loading: false });

  // Initial load
  useEffect(() => {
    dispatch(fetchTasks(filters));
  }, [dispatch, filters]);

  // Background silent polling + AI auto-trigger
  useTaskAutoTrigger({
    onAiStarted: (task) =>
      toast.success(`Task ${task.id.substring(0, 8)} finished! AI analysis started.`),
  });

  const handleFilterChange = (key, value) => dispatch(setFilters({ [key]: value }));

  // --- Cancel flow ---
  const handleCancel = (taskId) => {
    setConfirmState({ open: true, type: 'cancel', taskId, loading: false });
  };

  const doCancel = async () => {
    const { taskId } = confirmState;
    setConfirmState((s) => ({ ...s, loading: true }));
    try {
      await dispatch(cancelTask({ taskId, reason: 'Cancelled by user' })).unwrap();
      toast.success('任务已取消');
      dispatch(fetchTasks(filters));
    } catch (err) {
      toast.error('取消失败: ' + (err?.message || err));
    } finally {
      setConfirmState({ open: false, type: null, taskId: null, loading: false });
    }
  };

  // --- Delete flow ---
  const handleDelete = (taskId) => {
    setConfirmState({ open: true, type: 'delete', taskId, loading: false });
  };

  const doDelete = async () => {
    const { taskId } = confirmState;
    setConfirmState((s) => ({ ...s, loading: true }));
    try {
      await dispatch(deleteTask(taskId)).unwrap();
      toast.success('任务已删除');
      dispatch(fetchTasks(filters));
    } catch (err) {
      toast.error('删除失败: ' + (err?.message || err));
    } finally {
      setConfirmState({ open: false, type: null, taskId: null, loading: false });
    }
  };

  const filteredTasks = tasks.filter((t) => {
    const ts = t.status?.toLowerCase();
    const tp = t.priority?.toLowerCase();
    if (filters.status !== 'all' && ts !== filters.status) return false;
    if (filters.priority !== 'all' && tp !== filters.priority) return false;
    return true;
  });

  if (status === 'loading' && tasks.length === 0) {
    return <div className="flex items-center justify-center h-64"><Spinner size="lg" /></div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <motion.h1
            initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}
            className="text-3xl font-bold text-slate-900 dark:text-white"
          >
            Tasks
          </motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">Manage and monitor analysis tasks</p>
        </div>
        <Button onClick={() => dispatch(openModal({ type: 'createTask' }))}>➕ Create Task</Button>
      </div>

      {/* Filters */}
      <Card>
        <div className="flex flex-wrap gap-4">
          <FilterSelect label="Status" value={filters.status} onChange={(v) => handleFilterChange('status', v)}>
            <option value="all">All</option>
            {Object.values(TASK_STATUS).map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </FilterSelect>
          <FilterSelect label="Priority" value={filters.priority} onChange={(v) => handleFilterChange('priority', v)}>
            <option value="all">All</option>
            {Object.values(TASK_PRIORITY).map((p) => <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>)}
          </FilterSelect>
        </div>
      </Card>

      {/* Task list */}
      <Card>
        {error && (
          <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
            <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          </div>
        )}
        <TaskTable tasks={filteredTasks} onCancel={handleCancel} onDelete={handleDelete} />
      </Card>

      {/* Modal */}
      {modal.open && modal.type === 'createTask' && <CreateTaskModal />}

      {/* Cancel confirmation dialog */}
      <ConfirmDialog
        open={confirmState.open && confirmState.type === 'cancel'}
        onConfirm={doCancel}
        onCancel={() => setConfirmState({ open: false, type: null, taskId: null, loading: false })}
        title="取消任务"
        message="确定要取消此任务吗？正在运行的分析将被中止。"
        confirmText="取消任务"
        cancelText="返回"
        variant="warning"
        loading={confirmState.loading}
      />

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={confirmState.open && confirmState.type === 'delete'}
        onConfirm={doDelete}
        onCancel={() => setConfirmState({ open: false, type: null, taskId: null, loading: false })}
        title="删除任务"
        message="此操作将永久删除该任务及其所有分析数据（数据库文件、知识图谱等），且不可撤销。确定要继续吗？"
        confirmText="永久删除"
        cancelText="取消"
        variant="danger"
        loading={confirmState.loading}
      />
    </div>
  );
};

export default Tasks;

// ── Helpers ──────────────────────────────────────────────────────────────────

function FilterSelect({ label, value, onChange, children }) {
  const cls = 'block w-full pl-3 pr-10 py-2 text-base border-slate-300 dark:border-slate-600 focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm rounded-xl dark:bg-slate-700 dark:text-white';
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>{children}</select>
    </div>
  );
}
