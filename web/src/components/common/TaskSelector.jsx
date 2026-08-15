import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useSearchParams, useLocation } from 'react-router-dom';
import { fetchTasks, setCurrentTask } from '../../store/taskSlice';

const TaskSelector = () => {
    const dispatch = useDispatch();
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const { tasks, currentTask, status } = useSelector((state) => state.tasks);

    // 研判页面统一通过 query 参数（task_id/taskId）携带当前镜像
    const currentTaskId = searchParams.get('taskId') || searchParams.get('task_id') || currentTask?.id;

    const relevantPaths = ['/timeline', '/files', '/statistics', '/llm-descriptions', '/android', '/oss', '/case-report', '/knowledge-graph', '/case-intelligence', '/analysis-center', '/investigation'];
    const isRelevantPage = relevantPaths.some(path => location.pathname.startsWith(path));

    useEffect(() => {
        if (status === 'idle') {
            dispatch(fetchTasks());
        }
    }, [dispatch, status]);

    useEffect(() => {
        const urlTaskId = searchParams.get('taskId') || searchParams.get('task_id');
        if (urlTaskId && tasks.length > 0) {
            const task = tasks.find(t => t.id === urlTaskId);
            if (task && (!currentTask || currentTask.id !== urlTaskId)) {
                dispatch(setCurrentTask(task));
            }
        } else if (!urlTaskId && currentTask && isRelevantPage) {
            const paramName = location.pathname.startsWith('/case-report') ? 'taskId' : 'task_id';
            setSearchParams({ ...Object.fromEntries(searchParams), [paramName]: currentTask.id });
        }
    }, [searchParams, tasks, dispatch, currentTask, isRelevantPage, setSearchParams, location.pathname]);

    const handleTaskChange = (e) => {
        const newTaskId = e.target.value;

        const paramName = location.pathname.startsWith('/case-report') ? 'taskId' : 'task_id';

        if (newTaskId) {
            const newParams = Object.fromEntries(searchParams);
            // Clean up both possible names to avoid confusion
            delete newParams.taskId;
            delete newParams.task_id;
            newParams[paramName] = newTaskId;
            setSearchParams(newParams);
        } else {
            const newParams = Object.fromEntries(searchParams);
            delete newParams.taskId;
            delete newParams.task_id;
            setSearchParams(newParams);
        }
    };

    if (!isRelevantPage) return null;

    return (
        <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400 whitespace-nowrap hidden md:inline">
                Task:
            </span>
            <select
                value={currentTaskId || ''}
                onChange={handleTaskChange}
                className="block w-48 md:w-56 pl-3 pr-8 py-1.5 text-sm rounded-xl border-0 bg-white/50 dark:bg-slate-800/50 backdrop-blur-sm text-slate-700 dark:text-slate-200 ring-1 ring-slate-200/50 dark:ring-slate-700/50 focus:ring-2 focus:ring-primary-500/50 transition-all"
            >
                <option value="">Select task...</option>
                {tasks.map((task) => (
                    <option key={task.id} value={task.id}>
                        {task.image_path.split('/').pop()} ({task.id.substring(0, 8)}) - {task.status}
                    </option>
                ))}
            </select>
        </div>
    );
};

export default TaskSelector;
