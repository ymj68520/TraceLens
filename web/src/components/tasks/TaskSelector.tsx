import { useEffect } from 'react';
import { useSearchParams, useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../../store';
import { fetchTasks, setCurrentTask } from '../../store/taskSlice';
import { basename } from '../../lib/utils';

const TASK_PAGES = [
  '/timeline',
  '/files',
  '/statistics',
  '/android',
  '/oss',
  '/knowledge-graph',
  '/case-intelligence',
  '/analysis-center',
  '/investigation',
  '/memory',
  '/wechat-graph',
  '/search',
];

/** Task context switcher shown in the header on task-scoped pages. */
export default function TaskSelector() {
  const dispatch = useAppDispatch();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { tasks, currentTask, status } = useAppSelector((state) => state.tasks);

  const currentTaskId = searchParams.get('task_id') || searchParams.get('taskId') || currentTask?.id;

  const isRelevantPage = TASK_PAGES.some((path) => location.pathname.startsWith(path));

  useEffect(() => {
    if (status === 'idle') {
      void dispatch(fetchTasks({}));
    }
  }, [dispatch, status]);

  useEffect(() => {
    const urlTaskId = searchParams.get('task_id') || searchParams.get('taskId');
    if (urlTaskId && tasks.length > 0) {
      const task = tasks.find((t) => t.id === urlTaskId);
      if (task && currentTask?.id !== urlTaskId) {
        dispatch(setCurrentTask(task));
      }
    } else if (!urlTaskId && currentTask && isRelevantPage) {
      const next = Object.fromEntries(searchParams);
      next.task_id = currentTask.id;
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, tasks, dispatch, currentTask, isRelevantPage, setSearchParams]);

  const handleTaskChange = (value: string) => {
    const next = Object.fromEntries(searchParams);
    delete next.taskId;
    delete next.task_id;
    if (value) next.task_id = value;
    setSearchParams(next, { replace: true });
  };

  if (!isRelevantPage) return null;

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-ink-500 dark:text-ink-400 whitespace-nowrap hidden md:inline">
        任务
      </span>
      <select
        value={currentTaskId || ''}
        onChange={(e) => handleTaskChange(e.target.value)}
        className="select w-48 md:w-60 py-1.5 text-xs"
      >
        <option value="">选择任务…</option>
        {tasks.map((task) => (
          <option key={task.id} value={task.id}>
            {basename(task.image_path)} ({task.id.substring(0, 8)}) · {task.status}
          </option>
        ))}
      </select>
    </div>
  );
}
