/**
 * TaskTable
 *
 * Pure presentational component — renders the task list table.
 * All actions (cancel, delete) are passed in as callbacks.
 */
import { Link } from 'react-router-dom';
import Badge from '../common/Badge';
import ProgressBar from '../common/ProgressBar';
import { TASK_STATUS, TASK_PRIORITY, STATUS_COLORS, PRIORITY_COLORS } from '../../utils/constants';

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

function ActionsCell({ task, onCancel, onDelete }) {
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
          <Link to={`/case-report?task_id=${task.id}`} className="text-teal-600 hover:underline ml-1">Report</Link>
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

export default function TaskTable({ tasks, onCancel, onDelete }) {
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
            {['ID', 'Image Path', 'Status', 'Priority', 'Timeline', 'Progress', 'Actions'].map((h, i) => (
              <th key={h} className={`px-4 py-3 text-left text-xs font-medium text-slate-500 dark:text-slate-300 uppercase tracking-wider ${i === 0 ? 'w-20' : i === 2 ? 'w-28' : i === 3 ? 'w-24' : i === 4 ? 'w-44' : i === 5 ? 'w-40' : i === 6 ? 'w-48' : ''}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
          {tasks.map((task) => (
            <tr key={task.id} className="hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
              <td className="px-4 py-4 whitespace-nowrap text-[10px] font-mono text-slate-500 dark:text-slate-400">
                {task.id?.substring(0, 8)}
              </td>
              <td className="px-4 py-4 text-sm text-slate-900 dark:text-white truncate max-w-[200px]" title={task.image_path}>
                {task.image_path}
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
                <ActionsCell task={task} onCancel={onCancel} onDelete={onDelete} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
