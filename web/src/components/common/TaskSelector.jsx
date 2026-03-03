import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useSearchParams, useNavigate, useLocation } from 'react-router-dom';
import { fetchTasks, setCurrentTask } from '../../store/taskSlice';
import { TASK_STATUS, STATUS_COLORS } from '../../utils/constants';

const TaskSelector = () => {
    const dispatch = useDispatch();
    const navigate = useNavigate();
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const { tasks, currentTask, status } = useSelector((state) => state.tasks);

    const currentTaskId = searchParams.get('task_id') || currentTask?.id;

    const relevantPaths = ['/timeline', '/files', '/statistics', '/llm-descriptions', '/android', '/oss'];
    const isRelevantPage = relevantPaths.some(path => location.pathname.startsWith(path));

    useEffect(() => {
        if (status === 'idle') {
            dispatch(fetchTasks());
        }
    }, [dispatch, status]);

    useEffect(() => {
        if (searchParams.get('task_id') && tasks.length > 0) {
            const urlTaskId = searchParams.get('task_id');
            const task = tasks.find(t => t.id === urlTaskId);
            if (task && (!currentTask || currentTask.id !== urlTaskId)) {
                dispatch(setCurrentTask(task));
            }
        } else if (!searchParams.get('task_id') && currentTask && isRelevantPage) {
            setSearchParams({ ...Object.fromEntries(searchParams), task_id: currentTask.id });
        }
    }, [searchParams, tasks, dispatch, currentTask, isRelevantPage, setSearchParams]);

    const handleTaskChange = (e) => {
        const newTaskId = e.target.value;
        if (newTaskId) {
            setSearchParams({ ...Object.fromEntries(searchParams), task_id: newTaskId });
        } else {
            const newParams = Object.fromEntries(searchParams);
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
