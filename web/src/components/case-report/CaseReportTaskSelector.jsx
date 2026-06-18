// CaseReportTaskSelector.jsx
// Task-picker card shown on the Case Report page when no task is selected.

import Card from '../common/Card';
import Badge from '../common/Badge';

const CaseReportTaskSelector = ({ completedTasks, onSelect }) => (
    <Card title="📋 选择任务">
        {completedTasks.length === 0 ? (
            <div className="text-center py-8">
                <div className="text-5xl mb-4">🔍</div>
                <p className="text-slate-500 mb-4">
                    没有已完成的分析任务。
                </p>
                <p className="text-sm text-slate-400">
                    请先在{' '}
                    <a href="/tasks" className="text-primary-600 hover:text-blue-800 underline">
                        任务页面
                    </a>{' '}
                    创建并完成一个取证分析任务。
                </p>
            </div>
        ) : (
            <div className="space-y-3">
                <p className="text-sm text-slate-600 mb-4">
                    选择一个已完成的分析任务，开始 AI 案情分析：
                </p>
                <div className="space-y-2">
                    {completedTasks.map((task) => (
                        <button
                            key={task.id}
                            onClick={() => onSelect(task.id)}
                            className="w-full text-left p-4 border border-slate-200 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-all group"
                        >
                            <div className="flex items-center justify-between">
                                <div className="flex items-center space-x-3">
                                    <span className="text-xl">📊</span>
                                    <div>
                                        <p className="font-mono text-sm text-slate-700 group-hover:text-blue-700">
                                            {task.id.substring(0, 8)}...
                                        </p>
                                        <p className="text-sm text-slate-500 truncate max-w-md">
                                            {task.image_path}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex items-center space-x-2">
                                    <Badge variant="green">已完成</Badge>
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

export default CaseReportTaskSelector;
