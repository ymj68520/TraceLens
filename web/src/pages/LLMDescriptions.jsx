import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import { getTaskResults } from '../services/taskService';
import { fetchTasks } from '../store/taskSlice';

const LLMDescriptions = () => {
    const [searchParams, setSearchParams] = useSearchParams();
    const taskId = searchParams.get('task_id');

    const dispatch = useDispatch();
    const { tasks } = useSelector((state) => state.tasks);

    const [llmResults, setLlmResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [expandedItems, setExpandedItems] = useState({});

    const currentTask = tasks.find((t) => t.id === taskId);

    // Fetch tasks on mount for the task selector
    useEffect(() => {
        dispatch(fetchTasks({ status: 'all', priority: 'all' }));
    }, [dispatch]);

    // Fetch LLM results when taskId changes
    useEffect(() => {
        if (!taskId) {
            setLlmResults(null);
            setError(null);
            return;
        }

        const fetchData = async () => {
            setLoading(true);
            setError(null);

            try {
                const results = await getTaskResults(taskId);
                console.log('Task results:', results);

                if (results.llm_results) {
                    setLlmResults(results.llm_results);
                } else {
                    setError('No LLM analysis results found for this task. Make sure LLM analysis was enabled when creating the task.');
                }
            } catch (err) {
                console.error('Failed to fetch LLM results:', err);
                setError(err.message || 'Failed to load LLM analysis results');
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, [taskId]);

    // Filter tasks with LLM analysis enabled and completed
    const llmEnabledTasks = tasks.filter(
        (t) => t.llm_analyze && t.status === 'completed'
    );

    // Toggle expanded state for a file
    const toggleExpanded = (index) => {
        setExpandedItems((prev) => ({
            ...prev,
            [index]: !prev[index],
        }));
    };

    // Handle task selection
    const handleTaskSelect = (selectedTaskId) => {
        setSearchParams({ task_id: selectedTaskId });
    };

    // Filter descriptions based on search query
    const filteredDescriptions = llmResults?.descriptions?.filter((item) => {
        if (!searchQuery) return true;
        const query = searchQuery.toLowerCase();
        return (
            (item.file_path && item.file_path.toLowerCase().includes(query)) ||
            (item.summary && item.summary.toLowerCase().includes(query)) ||
            (item.description && item.description.toLowerCase().includes(query)) ||
            (item.keywords && item.keywords.toLowerCase().includes(query))
        );
    }) || [];

    // Parse keywords string into array
    const parseKeywords = (keywords) => {
        if (!keywords) return [];
        try {
            const parsed = JSON.parse(keywords);
            return Array.isArray(parsed) ? parsed : [keywords];
        } catch {
            return keywords.split(',').map((k) => k.trim()).filter(Boolean);
        }
    };

    // Format date
    const formatDate = (dateStr) => {
        if (!dateStr) return '-';
        try {
            return new Date(dateStr).toLocaleString();
        } catch {
            return dateStr;
        }
    };

    // Task Selector Component
    const TaskSelector = () => (
        <Card title="📋 Select a Task">
            {llmEnabledTasks.length === 0 ? (
                <div className="text-center py-8">
                    <div className="text-5xl mb-4">🔍</div>
                    <p className="text-gray-500 mb-4">
                        No completed tasks with LLM analysis found.
                    </p>
                    <p className="text-sm text-gray-400">
                        Create a task with LLM analysis enabled from the{' '}
                        <a href="/tasks" className="text-blue-600 hover:text-blue-800 underline">
                            Tasks page
                        </a>{' '}
                        or use the task selector in the top bar to see AI file descriptions here.
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    <p className="text-sm text-gray-600 mb-4">
                        Select a completed task with LLM analysis to view AI-generated file descriptions:
                    </p>
                    <div className="space-y-2">
                        {llmEnabledTasks.map((task) => (
                            <button
                                key={task.id}
                                onClick={() => handleTaskSelect(task.id)}
                                className="w-full text-left p-4 border border-gray-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 transition-all group"
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center space-x-3">
                                        <span className="text-xl">📊</span>
                                        <div>
                                            <p className="font-mono text-sm text-gray-700 group-hover:text-blue-700">
                                                {task.id.substring(0, 8)}...
                                            </p>
                                            <p className="text-sm text-gray-500 truncate max-w-md">
                                                {task.image_path}
                                            </p>
                                        </div>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <Badge variant="green">Completed</Badge>
                                        <Badge variant="purple">LLM</Badge>
                                        <span className="text-blue-500 opacity-0 group-hover:opacity-100 transition-opacity">
                                            →
                                        </span>
                                    </div>
                                </div>
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </Card>
    );

    // No task selected - show task selector
    if (!taskId) {
        return (
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">🤖 AI File Descriptions</h1>
                    <p className="mt-2 text-gray-600">View AI-generated descriptions for analyzed files</p>
                </div>
                <TaskSelector />
            </div>
        );
    }

    // Loading state
    if (loading) {
        return (
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">🤖 AI File Descriptions</h1>
                    <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
                </div>
                <Card>
                    <div className="flex items-center justify-center h-64">
                        <Spinner size="lg" />
                        <span className="ml-4 text-gray-600">Loading AI analysis results...</span>
                    </div>
                </Card>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div className="space-y-6">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">🤖 AI File Descriptions</h1>
                    <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
                </div>

                <Card title="Error">
                    <div className="p-4 bg-red-50 border border-red-200 rounded-md">
                        <p className="text-red-800">{error}</p>
                    </div>
                </Card>

                {/* Show task selector below the error */}
                <TaskSelector />
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">🤖 AI File Descriptions</h1>
                    <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
                    {currentTask && (
                        <div className="mt-2">
                            <Badge variant="blue">{currentTask.status}</Badge>
                            {currentTask.llm_analyze && (
                                <Badge variant="purple" className="ml-2">LLM Analysis</Badge>
                            )}
                        </div>
                    )}
                </div>
                <button
                    onClick={() => setSearchParams({})}
                    className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
                >
                    ← Back to Task List
                </button>
            </div>

            {/* Statistics */}
            <Card title="📊 Analysis Statistics">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-blue-50 rounded-lg p-4">
                        <p className="text-sm text-blue-600 font-medium">Total Files Analyzed</p>
                        <p className="text-2xl font-bold text-blue-900">
                            {llmResults?.stats?.total_analyzed || llmResults?.descriptions?.length || 0}
                        </p>
                    </div>
                    <div className="bg-green-50 rounded-lg p-4">
                        <p className="text-sm text-green-600 font-medium">Matching Search</p>
                        <p className="text-2xl font-bold text-green-900">
                            {filteredDescriptions.length}
                        </p>
                    </div>
                    <div className="bg-purple-50 rounded-lg p-4">
                        <p className="text-sm text-purple-600 font-medium">Analysis Mode</p>
                        <p className="text-2xl font-bold text-purple-900">
                            {currentTask?.llm_mode || 'smart'}
                        </p>
                    </div>
                </div>
            </Card>

            {/* Search */}
            <Card>
                <div className="flex items-center space-x-2">
                    <span className="text-lg">🔍</span>
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search by file name, summary, or keywords..."
                        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                    {searchQuery && (
                        <button
                            onClick={() => setSearchQuery('')}
                            className="px-3 py-2 text-gray-500 hover:text-gray-700"
                        >
                            ✕
                        </button>
                    )}
                </div>
            </Card>

            {/* File Descriptions List */}
            <Card title={`📄 File Descriptions (${filteredDescriptions.length})`}>
                {filteredDescriptions.length === 0 ? (
                    <div className="text-center py-12 text-gray-500">
                        {searchQuery
                            ? 'No files match your search criteria.'
                            : 'No AI descriptions available.'}
                    </div>
                ) : (
                    <div className="space-y-4">
                        {filteredDescriptions.map((item, index) => (
                            <div
                                key={index}
                                className="border border-gray-200 rounded-lg p-4 hover:border-blue-300 hover:shadow-sm transition-all"
                            >
                                {/* File Path */}
                                <div className="flex items-start justify-between">
                                    <div className="flex items-center space-x-2 flex-1 min-w-0">
                                        <span className="text-lg">📄</span>
                                        <p className="font-mono text-sm text-gray-900 truncate" title={item.file_path}>
                                            {item.file_path}
                                        </p>
                                    </div>
                                    <span className="text-xs text-gray-400 ml-2 whitespace-nowrap">
                                        {formatDate(item.created_at)}
                                    </span>
                                </div>

                                {/* Summary */}
                                {item.summary && (
                                    <div className="mt-3">
                                        <p className="text-sm font-medium text-gray-700">Summary:</p>
                                        <p className="text-sm text-gray-600 mt-1">{item.summary}</p>
                                    </div>
                                )}

                                {/* Keywords */}
                                {item.keywords && (
                                    <div className="mt-3">
                                        <div className="flex flex-wrap gap-2">
                                            {parseKeywords(item.keywords).map((keyword, idx) => (
                                                <span
                                                    key={idx}
                                                    className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800"
                                                >
                                                    {keyword}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Full Description (Expandable) */}
                                {item.description && (
                                    <div className="mt-3">
                                        <button
                                            onClick={() => toggleExpanded(index)}
                                            className="flex items-center text-sm text-blue-600 hover:text-blue-800"
                                        >
                                            <span className="mr-1">{expandedItems[index] ? '▼' : '▶'}</span>
                                            {expandedItems[index] ? 'Hide' : 'Show'} full description
                                        </button>
                                        {expandedItems[index] && (
                                            <div className="mt-2 p-3 bg-gray-50 rounded-md">
                                                <p className="text-sm text-gray-700 whitespace-pre-wrap">
                                                    {item.description}
                                                </p>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </Card>
        </div>
    );
};

export default LLMDescriptions;
