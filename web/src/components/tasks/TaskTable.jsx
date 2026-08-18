/**
 * TaskTable
 *
 * Pure presentational component — renders the task list table.
 * All actions (cancel, delete) are passed in as callbacks.
 */
import { Link } from 'react-router-dom';
import Badge from '../common/Badge';
import ProgressBar from '../common/ProgressBar';
import { STATUS_COLORS, PRIORITY_COLORS } from '../../utils/constants';

/** Helper: convert timestamp (ms or s) to locale string */
function formatDate(timestamp) {
  if (!timestamp || timestamp === 0) return '-';
  const date = timestamp > 1e12 ? new Date(timestamp) : new Date(timestamp * 1000);
  return date.toLocaleString();
}

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status?.toLowerCase()]?.split('-')[1] || 'gray';
  return <Badge variant={color}>{status}</Badge>;
}

function PriorityBadge({ priority }) {
  const color = PRIORITY_COLORS[priority?.toLowerCase()]?.split('-')[1] || 'gray';
  return <Badge variant={color}>{priority}</Badge>;
}

function ProgressCell({ task }) {
  if (task.status?.toLowerCase() !== 'running') {
    return (
      <span className="text-xs text-slate-500 dark:text-slate-400">
        {task.status?.toLowerCase() === 'completed' ? '100%' : '-'}
      </span>
    );
  }
  return (
    <div className="w-full">
      <ProgressBar value={task.progress?.overall_percentage || 0} showLabel={false} size="xs" />
      <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 truncate">
        {task.progress?.phase_description || 'Processing...'}
      </p>
    </div>
  );
}

function ActionsCell({ task, onCancel, onDelete, onJoinCase }) {
  const status = task.status?.toLowerCase();
  const finished = ['completed', 'failed', 'cancelled'].includes(status);
  return (
    <div className="flex items-center space-x-1 text-xs font-medium">
      {status === 'running' && (
        <button onClick={() => onCancel(task.id)} className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300">
          Cancel
        </button>
      )}
      {status === 'completed' && (
        <>
          <Link to={`/timeline?task_id=${task.id}`} className="text-primary-600 hover:underline">Timeline</Link>
          <Link to={`/files?task_id=${task.id}`} className="text-green-600 hover:underline ml-1">Files</Link>
          <Link to={`/reports/task/${task.id}`} className="text-teal-600 hover:underline ml-1">Report</Link>
          <button onClick={() => onJoinCase(task.id)} className="text-indigo-600 hover:underline ml-1" title="将此任务加入多镜像案件">
            加入案件
          </button>
        </>
      )}
      {finished && (
        <button onClick={() => onDelete(task.id)} className="text-slate-400 hover:text-red-600 ml-2" title="Delete task">
          🗑️
        </button>
      )}
    </div>
  );
}

export default function TaskTable({ tasks, onCancel, onDelete, onJoinCase, taskCaseMap = {}, selectedTaskIds, onToggleSelect, onToggleSelectAll }) {
  // Multi-select is opt-in: only rendered when selectedTaskIds is provided.
  const selectable = Array.isArray(selectedTaskIds) || selectedTaskIds instanceof Set;
  const isSel = (id) => selectable && (selectedTaskIds.has ? selectedTaskIds.has(id) : selectedTaskIds.includes(id));
  const completedIds = tasks.filter((t) => t.status?.toLowerCase() === 'completed').map((t) => t.id);
  const allSelected = selectable && completedIds.length > 0 && completedIds.every((id) => isSel(id));

  if (tasks.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-500 dark:text-slate-400">No tasks found. Create your first task to get started.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto overflow-y-hidden">
      <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700 table-fixed">
        <thead className="bg-slate-50 dark:bg-slate-900/50">
          <tr>
            {selectable && (
              <th className="px-4 py-3 w-10">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(e) => onToggleSelectAll && onToggleSelectAll(e.target.checked)}
                  className="h-4 w-4 text-primary-600 rounded"
                  title="全选已完成任务"
                />
              </th>
            )}
            {['ID', 'Image Path', 'Status', 'Priority', 'Timeline', 'Progress', 'Actions'].map((h, i) => (
              <th key={h} className={`px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider ${i === 0 ? 'w-20' : i === 2 ? 'w-28' : i === 3 ? 'w-24' : i === 4 ? 'w-44' : i === 5 ? 'w-40' : i === 6 ? 'w-48' : ''}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
          {tasks.map((task) => {
            const forensicCase = taskCaseMap[task.id];
            const isCompleted = task.status?.toLowerCase() === 'completed';
            const selected = isSel(task.id);
            return (
            <tr key={task.id} className={`hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors ${selected ? 'bg-primary-50/60 dark:bg-primary-900/20' : ''}`}>
              {selectable && (
                <td className="px-4 py-4 whitespace-nowrap">
                  <input
                    type="checkbox"
                    disabled={!isCompleted}
                    checked={selected}
                    onChange={() => onToggleSelect && onToggleSelect(task.id)}
                    className="h-4 w-4 text-primary-600 rounded disabled:opacity-30"
                    title={isCompleted ? '勾选后可组建案件' : '仅已完成任务可选'}
                  />
                </td>
              )}
              <td className="px-4 py-4 whitespace-nowrap text-[10px] font-mono text-slate-500 dark:text-slate-400">
                {task.id?.substring(0, 8)}
              </td>
              <td className="px-4 py-4 text-sm text-slate-900 dark:text-white truncate max-w-[200px]" title={task.image_path}>
                <div className="truncate">{task.image_path}</div>
                {forensicCase && (
                  <Link to={`/reports/case/${forensicCase.id}`}
                    className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-200 dark:border-indigo-700 text-[10px] text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-800/40 transition-colors"
                    title={`所属案件：${forensicCase.name}`}>
                    🗂 {forensicCase.name}
                  </Link>
                )}
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <StatusBadge status={task.status} />
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <PriorityBadge priority={task.priority} />
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
                <ProgressCell task={task} />
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <ActionsCell task={task} onCancel={onCancel} onDelete={onDelete} onJoinCase={onJoinCase} />
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
