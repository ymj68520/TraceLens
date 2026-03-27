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

import { startCaseAnalysis, getCaseReport } from '../services/caseAnalysisService';

const Tasks = () => {
  const dispatch = useDispatch();
  const { tasks, status, error, filters } = useSelector((state) => state.tasks);
  const { modal } = useSelector((state) => state.ui);
  const { autoRefresh, refreshInterval } = useSelector((state) => state.settings);
  const toast = useToast();
  
  // Track which tasks have already triggered AI analysis to prevent loops
  const [triggeredAiTasks, setTriggeredAiTasks] = useState(new Set());
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [taskData, setTaskData] = useState({
    image_path: '',
    priority: 'normal',
    android_analyze: false,
    windows_analyze: false,
    linux_analyze: false,
    xfs_mode: 'auto',
    llm_analyze: false,
    llm_mode: 'smart',
    case_description: '',
  });
  const [createError, setCreateError] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    dispatch(fetchTasks(filters));
  }, [dispatch, filters]);

  // Auto-refresh and Automatic AI Trigger
  useEffect(() => {
    if (!autoRefresh) return;

    const interval = setInterval(async () => {
      try {
        const result = await dispatch(fetchTasks(filters)).unwrap();
        const currentTasks = result.tasks || [];

        // Protection: On first load, mark existing tasks as "seen" but don't trigger AI
        if (isInitialLoad) {
          const initialSet = new Set();
          currentTasks.forEach(t => {
            if (t.status?.toLowerCase() === 'completed') initialSet.add(t.id);
          });
          setTriggeredAiTasks(initialSet);
          setIsInitialLoad(false);
          return;
        }

        // Subsequent polls: Trigger only for new completions
        for (const task of currentTasks) {
          const taskStatus = task.status?.toLowerCase();
          if (
            taskStatus === 'completed' && 
            task.llm_analyze && 
            !triggeredAiTasks.has(task.id)
          ) {
            setTriggeredAiTasks(prev => new Set(prev).add(task.id));
            
            try {
              const report = await getCaseReport(task.id);
              if (report && report.report) continue;
            } catch (e) {
              try {
                await startCaseAnalysis({
                  taskId: task.id,
                  filesDbPath: task.output_files_db,
                  caseDescription: task.case_description || '自动分析',
                  maxFilterFiles: 200
                });
                toast.success(`Task ${task.id.substring(0,8)} finished! AI analysis started.`);
              } catch (err) {
                console.error('Failed to auto-trigger AI:', err);
              }
            }
          }
        }
      } catch (err) {
        console.error('Refresh error:', err);
      }
    }, refreshInterval || 5000);

    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, dispatch, filters, toast, triggeredAiTasks, isInitialLoad]);

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
        case_description: '',
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

  const formatDate = (timestamp) => {
    if (!timestamp || timestamp === 0) return '-';
    // If it's a Unix timestamp in seconds, convert to ms
    const date = new Date(timestamp * 1000);
    return date.toLocaleString();
  };

  const filteredTasks = tasks.filter((task) => {
    const taskStatus = task.status?.toLowerCase();
    const filterStatus = filters.status?.toLowerCase();
    const taskPriority = task.priority?.toLowerCase();
    const filterPriority = filters.priority?.toLowerCase();

    if (filterStatus !== 'all' && taskStatus !== filterStatus) return false;
    if (filterPriority !== 'all' && taskPriority !== filterPriority) return false;
    return true;
  });

  console.log('Tasks diagnostics:', { 
    totalTasksCount: tasks.length, 
    filteredTasksCount: filteredTasks.length,
    filters,
    rawTasks: tasks 
  });

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
          <div className="overflow-x-auto overflow-y-hidden">
            <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700 table-fixed">
              <thead className="bg-slate-50 dark:bg-slate-900/50">
                <tr>
                  <th className="w-20 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Image Path
                  </th>
                  <th className="w-28 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="w-24 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Priority
                  </th>
                  <th className="w-44 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Timeline
                  </th>
                  <th className="w-40 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="w-48 px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
                {filteredTasks.map((task) => (
                  <tr key={task.id} className="hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
                    <td className="px-4 py-4 whitespace-nowrap text-[10px] font-mono text-slate-500 dark:text-slate-400">
                      {task.id?.substring(0, 8)}
                    </td>
                    <td className="px-4 py-4 text-sm text-slate-900 dark:text-white truncate max-w-[200px]" title={task.image_path}>
                      {task.image_path}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <Badge variant={STATUS_COLORS[task.status?.toLowerCase()]?.split('-')[1] || 'gray'}>
                        {task.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      <Badge variant={PRIORITY_COLORS[task.priority?.toLowerCase()]?.split('-')[1] || 'gray'}>
                        {task.priority}
                      </Badge>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap leading-tight">
                      <div className="flex flex-col space-y-1">
                        <div className="flex items-center text-[10px] text-slate-400">
                          <span className="w-8 uppercase">Start:</span>
                          <span className="text-slate-600 dark:text-slate-300 font-medium">{formatDate(task.timestamps?.created)}</span>
                        </div>
                        <div className="flex items-center text-[10px] text-slate-400">
                          <span className="w-8 uppercase">End:</span>
                          <span className="text-slate-600 dark:text-slate-300 font-medium">{formatDate(task.timestamps?.completed)}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap">
                      {task.status?.toLowerCase() === 'running' ? (
                        <div className="w-full">
                          <ProgressBar
                            value={task.progress?.overall_percentage || 0}
                            showLabel={false}
                            size="xs"
                          />
                          <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 truncate">
                            {task.progress?.phase_description || 'Processing...'}
                          </p>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          {task.status?.toLowerCase() === 'completed' ? '100%' : '-'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-4 whitespace-nowrap text-xs font-medium space-x-1">
                      {task.status?.toLowerCase() === 'running' && (
                        <button
                          onClick={() => handleCancelTask(task.id)}
                          className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                        >
                          Cancel
                        </button>
                      )}
                      {task.status?.toLowerCase() === 'completed' && (
                        <div className="flex items-center space-x-2">
                          <Link to={`/timeline?task_id=${task.id}`} className="text-primary-600 hover:underline">Timeline</Link>
                          <Link to={`/files?task_id=${task.id}`} className="text-green-600 hover:underline">Files</Link>
                          {task.llm_analyze && <Link to={`/case-report?task_id=${task.id}`} className="text-teal-600 hover:underline">Report</Link>}
                        </div>
                      )}
                      {(['completed', 'failed', 'cancelled'].includes(task.status?.toLowerCase())) && (
                        <button
                          onClick={() => handleDeleteTask(task.id)}
                          className="text-slate-400 hover:text-red-600 ml-2"
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
                {taskData.llm_analyze && (
                  <div className="ml-6 mt-2 space-y-2">
                    <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                      案情描述
                    </label>
                    <textarea
                      id="case-description-textarea"
                      value={taskData.case_description}
                      disabled={isCreating}
                      onChange={(e) => setTaskData({ ...taskData, case_description: e.target.value })}
                      className="w-full px-3 py-2 h-24 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm resize-none"
                      placeholder="请输入案情描述，例如：一起涉嫌网络诈骗案件..."
                    />
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      案情描述将用于 AI 智能筛选相关文件并生成分析报告
                    </p>
                  </div>
                )}
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
