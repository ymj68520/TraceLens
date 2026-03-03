import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Link } from 'react-router-dom';
import { fetchTasks, cancelTask, createTask, setFilters, deleteTask } from '../store/taskSlice';
import { openModal, closeModal } from '../store/uiSlice';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import ProgressBar from '../components/common/ProgressBar';
import Spinner from '../components/common/Spinner';
import { useToast } from '../components/common/ToastContext';
import { TASK_STATUS, TASK_PRIORITY, STATUS_COLORS, PRIORITY_COLORS } from '../utils/constants';

const Tasks = () => {
  const dispatch = useDispatch();
  const { tasks, status, error, filters } = useSelector((state) => state.tasks);
  const { modal } = useSelector((state) => state.ui);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);
  const toast = useToast();
  const [taskData, setTaskData] = useState({
    image_path: '',
    priority: 'normal',
    android_analyze: false,
    windows_analyze: false,
    linux_analyze: false,
    xfs_mode: 'auto',
    llm_analyze: false,
    llm_mode: 'smart',
  });
  const [createError, setCreateError] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    dispatch(fetchTasks(filters))
      .then((result) => {
        console.log('fetchTasks result:', result);
      })
      .catch((err) => {
        console.error('fetchTasks error:', err);
      });
  }, [dispatch, filters]);

  // Auto-refresh for running tasks
  useEffect(() => {
    if (!autoRefresh) return;

    const hasRunningTasks = tasks.some(t => t.status === TASK_STATUS.RUNNING);
    if (!hasRunningTasks) return;

    const interval = setInterval(() => {
      dispatch(fetchTasks(filters));
    }, refreshInterval || 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, tasks, dispatch, filters]);

  const handleFilterChange = (filterType, value) => {
    dispatch(setFilters({ [filterType]: value }));
  };

  const handleCreateTask = async (e) => {
    e.preventDefault();
    setCreateError('');
    setIsCreating(true);

    try {
      const result = await dispatch(createTask(taskData)).unwrap();
      console.log('Task created successfully:', result);

      // Close modal and reset form
      dispatch(closeModal());
      setTaskData({
        image_path: '',
        priority: 'normal',
        android_analyze: false,
        windows_analyze: false,
        linux_analyze: false,
        xfs_mode: 'auto',
        llm_analyze: false,
        llm_mode: 'smart',
      });

      // Refresh task list
      dispatch(fetchTasks(filters));

      // Show success message
      toast.success('Task created successfully! Check the task list for progress.');
    } catch (err) {
      console.error('Failed to create task:', err);
      const errorMessage = err?.message || err?.toString?.() || String(err) || 'Failed to create task. Please try again.';
      setCreateError(errorMessage);
    } finally {
      setIsCreating(false);
    }
  };

  const handleCancelTask = async (taskId) => {
    if (window.confirm('Are you sure you want to cancel this task?')) {
      try {
        await dispatch(cancelTask({ taskId, reason: 'Cancelled by user' })).unwrap();
        toast.success('Task cancelled successfully.');
        dispatch(fetchTasks(filters));
      } catch (err) {
        toast.error('Failed to cancel task: ' + (err?.message || err));
      }
    }
  };

  const handleDeleteTask = async (taskId) => {
    if (window.confirm('Are you sure you want to delete this task? This action cannot be undone.')) {
      try {
        await dispatch(deleteTask(taskId)).unwrap();
        toast.success('Task deleted successfully.');
        dispatch(fetchTasks(filters));
      } catch (err) {
        toast.error('Failed to delete task: ' + (err?.message || err));
      }
    }
  };

  const filteredTasks = tasks.filter((task) => {
    if (filters.status !== 'all' && task.status !== filters.status) return false;
    if (filters.priority !== 'all' && task.priority !== filters.priority) return false;
    return true;
  });

  console.log('Tasks state:', { tasks, status, error, filters });
  console.log('Filtered tasks:', filteredTasks);

  if (status === 'loading' && tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-white">Tasks</motion.h1>
          <p className="mt-2 text-slate-600 dark:text-slate-300">Manage and monitor analysis tasks</p>
        </div>
        <Button onClick={() => dispatch(openModal({ type: 'createTask' }))}>
          ➕ Create Task
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <div className="flex flex-wrap gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Status
            </label>
            <select
              value={filters.status}
              onChange={(e) => handleFilterChange('status', e.target.value)}
              className="block w-full pl-3 pr-10 py-2 text-base border-slate-300 dark:border-slate-600 focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm rounded-xl dark:bg-slate-700 dark:text-white"
            >
              <option value="all">All</option>
              <option value={TASK_STATUS.PENDING}>Pending</option>
              <option value={TASK_STATUS.RUNNING}>Running</option>
              <option value={TASK_STATUS.COMPLETED}>Completed</option>
              <option value={TASK_STATUS.FAILED}>Failed</option>
              <option value={TASK_STATUS.CANCELLED}>Cancelled</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Priority
            </label>
            <select
              value={filters.priority}
              onChange={(e) => handleFilterChange('priority', e.target.value)}
              className="block w-full pl-3 pr-10 py-2 text-base border-slate-300 dark:border-slate-600 focus:outline-none focus:ring-primary-500 focus:border-primary-500 sm:text-sm rounded-xl dark:bg-slate-700 dark:text-white"
            >
              <option value="all">All</option>
              <option value={TASK_PRIORITY.LOW}>Low</option>
              <option value={TASK_PRIORITY.NORMAL}>Normal</option>
              <option value={TASK_PRIORITY.HIGH}>High</option>
              <option value={TASK_PRIORITY.CRITICAL}>Critical</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Task List */}
      <Card>
        {error && (
          <div className="mb-4 p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
            <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          </div>
        )}

        {filteredTasks.length === 0 ? (
          <div className="text-center py-12">
            <p className="text-slate-500 dark:text-slate-400">No tasks found. Create your first task to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
              <thead className="bg-slate-50 dark:bg-slate-800">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Task ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Image Path
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Priority
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                {filteredTasks.map((task) => (
                  <tr key={task.id} className="hover:bg-slate-50 dark:hover:bg-slate-700">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-900 dark:text-white">
                      {task.id?.substring(0, 8)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
                      {task.image_path}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge variant={STATUS_COLORS[task.status]?.split('-')[1] || 'gray'}>
                        {task.status}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge variant={PRIORITY_COLORS[task.priority]?.split('-')[1] || 'gray'}>
                        {task.priority}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {task.status === TASK_STATUS.RUNNING ? (
                        <div className="w-48">
                          <ProgressBar
                            value={task.progress?.overall_percentage || 0}
                            showLabel={false}
                            size="sm"
                          />
                          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                            {task.progress?.phase_description || 'Processing...'}
                          </p>
                        </div>
                      ) : (
                        <span className="text-sm text-slate-500 dark:text-slate-400">
                          {task.status === TASK_STATUS.COMPLETED ? '100%' : '-'}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                      {task.status === TASK_STATUS.RUNNING && (
                        <button
                          onClick={() => handleCancelTask(task.id)}
                          className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                        >
                          Cancel
                        </button>
                      )}
                      {task.status === TASK_STATUS.COMPLETED && (
                        <>
                          <Link
                            to={`/timeline?task_id=${task.id}`}
                            className="text-primary-600 hover:text-blue-900 dark:text-primary-400 dark:hover:text-blue-300"
                          >
                            Timeline
                          </Link>
                          <Link
                            to={`/files?task_id=${task.id}`}
                            className="text-green-600 hover:text-green-900 ml-2 dark:text-green-400 dark:hover:text-green-300"
                          >
                            Files
                          </Link>
                          <Link
                            to={`/statistics?task_id=${task.id}`}
                            className="text-purple-600 hover:text-purple-900 ml-2 dark:text-purple-400 dark:hover:text-purple-300"
                          >
                            Stats
                          </Link>
                          {task.llm_analyze && (
                            <Link
                              to={`/llm-descriptions?task_id=${task.id}`}
                              className="text-orange-600 hover:text-orange-900 ml-2 dark:text-orange-400 dark:hover:text-orange-300"
                            >
                              AI
                            </Link>
                          )}
                        </>
                      )}
                      {/* Delete button for completed, failed, or cancelled tasks */}
                      {(task.status === TASK_STATUS.COMPLETED ||
                        task.status === TASK_STATUS.FAILED ||
                        task.status === TASK_STATUS.CANCELLED) && (
                          <button
                            onClick={() => handleDeleteTask(task.id)}
                            className="text-slate-400 hover:text-red-600 ml-2 dark:hover:text-red-400"
                            title="Delete task"
                          >
                            🗑️
                          </button>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Create Task Modal */}
      {modal.open && modal.type === 'createTask' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black bg-opacity-50">
          <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
              <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Create New Task</h2>
              <button
                onClick={() => dispatch(closeModal())}
                className="text-slate-400 hover:text-slate-500 dark:hover:text-slate-300"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateTask} className="px-6 py-4 space-y-4">
              {createError && (
                <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
                  <p className="text-sm text-red-800 dark:text-red-200">{createError}</p>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Image Path *
                </label>
                <input
                  type="text"
                  required
                  disabled={isCreating}
                  value={taskData.image_path}
                  onChange={(e) => setTaskData({ ...taskData, image_path: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white"
                  placeholder="/path/to/disk_image.dd"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Priority
                </label>
                <select
                  value={taskData.priority}
                  disabled={isCreating}
                  onChange={(e) => setTaskData({ ...taskData, priority: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white"
                >
                  <option value="low">Low</option>
                  <option value="normal">Normal</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  XFS Mode
                </label>
                <select
                  value={taskData.xfs_mode}
                  disabled={isCreating}
                  onChange={(e) => setTaskData({ ...taskData, xfs_mode: e.target.value })}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white"
                >
                  <option value="auto">Auto</option>
                  <option value="native">Native (Linux only)</option>
                  <option value="pure">Pure (Cross-platform)</option>
                </select>
              </div>
              <div className="space-y-2">
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={taskData.android_analyze}
                    disabled={isCreating}
                    onChange={(e) => setTaskData({ ...taskData, android_analyze: e.target.checked })}
                    className="rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                  />
                  <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">Android Analysis</span>
                </label>
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={taskData.llm_analyze}
                    disabled={isCreating}
                    onChange={(e) => setTaskData({ ...taskData, llm_analyze: e.target.checked })}
                    className="rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                  />
                  <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">LLM Analysis</span>
                </label>
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={taskData.windows_analyze}
                    disabled={isCreating}
                    onChange={(e) => setTaskData({ ...taskData, windows_analyze: e.target.checked })}
                    className="rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                  />
                  <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">Windows Analysis</span>
                </label>
                <label className="flex items-center">
                  <input
                    type="checkbox"
                    checked={taskData.linux_analyze}
                    disabled={isCreating}
                    onChange={(e) => setTaskData({ ...taskData, linux_analyze: e.target.checked })}
                    className="rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                  />
                  <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">Linux Analysis</span>
                </label>
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => dispatch(closeModal())}
                  disabled={isCreating}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isCreating}>
                  {isCreating ? 'Creating...' : 'Create Task'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Tasks;
