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

    // Only show on relevant pages
    const relevantPaths = ['/timeline', '/files', '/statistics', '/llm-descriptions', '/android'];
    const isRelevantPage = relevantPaths.some(path => location.pathname.startsWith(path));

    useEffect(() => {
        if (status === 'idle') {
            dispatch(fetchTasks());
        }
    }, [dispatch, status]);

    // Sync current task with URL
    useEffect(() => {
        // 1. URL -> Redux: If URL has task_id, update Redux
        if (searchParams.get('task_id') && tasks.length > 0) {
            const urlTaskId = searchParams.get('task_id');
            const task = tasks.find(t => t.id === urlTaskId);
            if (task && (!currentTask || currentTask.id !== urlTaskId)) {
                dispatch(setCurrentTask(task));
            }
        }
        // 2. Redux -> URL: If URL missing task_id but Redux has it, update URL (on relevant pages)
        else if (!searchParams.get('task_id') && currentTask && isRelevantPage) {
            setSearchParams({ ...Object.fromEntries(searchParams), task_id: currentTask.id });
        }
    }, [searchParams, tasks, dispatch, currentTask, isRelevantPage, setSearchParams]);

    const handleTaskChange = (e) => {
        const newTaskId = e.target.value;
        if (newTaskId) {
            // Update URL
            setSearchParams({ ...Object.fromEntries(searchParams), task_id: newTaskId });
        } else {
            const newParams = Object.fromEntries(searchParams);
            delete newParams.task_id;
            setSearchParams(newParams);
        }
    };

    if (!isRelevantPage) return null;

    return (
        <div className="flex items-center space-x-2 mr-4">
            <span className="text-sm font-medium text-gray-700 whitespace-nowrap">Current Task:</span>
            <select
                value={currentTaskId || ''}
                onChange={handleTaskChange}
                className="block w-64 pl-3 pr-10 py-1.5 text-sm border-gray-300 focus:outline-none focus:ring-blue-500 focus:border-blue-500 rounded-md"
            >
                <option value="">Select a task...</option>
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
