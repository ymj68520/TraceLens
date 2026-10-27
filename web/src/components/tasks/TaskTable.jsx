import { forensicLabel, taskPhaseLabel } from '../../utils/forensicLabels';
/**
 * TaskTable
 *
 * Pure presentational component — renders the task list table.
 * All actions (cancel, delete) are passed in as callbacks.
 */
import { Fragment } from 'react';
import { Link } from 'react-router-dom';
import Badge from '../common/Badge';
import ProgressBar from '../common/ProgressBar';
import { useTranslation } from '../../hooks/useTranslation';
import { STATUS_COLORS, PRIORITY_COLORS, taskStatusZh, taskPriorityZh } from '../../utils/constants';

/** Helper: convert timestamp (ms or s) to locale string */
function formatDate(timestamp) {
  if (!timestamp || timestamp === 0) return '-';
  const date = timestamp > 1e12 ? new Date(timestamp) : new Date(timestamp * 1000);
  return date.toLocaleString('zh-CN');
}

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status?.toLowerCase()]?.split('-')[1] || 'gray';
  return <Badge variant={color}>{forensicLabel(status)}</Badge>;
}

function PriorityBadge({ priority }) {
  const color = PRIORITY_COLORS[priority?.toLowerCase()]?.split('-')[1] || 'gray';
  return <Badge variant={color}>{forensicLabel(priority)}</Badge>;
}

function ProgressCell({ task }) {
  const status = task.status?.toLowerCase();
  // A resumable stop keeps its progress: showing "-" would suggest the work was
  // lost, and the whole point of the ledger is that it was not.
  if (status === 'interrupted' || status === 'paused') {
    const pct = task.progress?.overall_percentage || 0;
    return (
      <div className="w-full">
        <ProgressBar value={pct} showLabel={false} size="xs" />
        <p className="text-[10px] text-amber-700 dark:text-amber-400 mt-1 truncate">
          {pct}% · 已完成阶段保留，可从断点继续
        </p>
      </div>
    );
  }
  if (status !== 'running') {
    return (
      <span className="text-xs text-slate-500 dark:text-slate-400">
        {status === 'completed' ? '100%' : '-'}
      </span>
    );
  }
  return (
    <div className="w-full">
      <ProgressBar value={task.progress?.overall_percentage || 0} showLabel={false} size="xs" />
      <p className="text-[10px] text-slate-500 dark:text-slate-400 mt-1 truncate">
        {task.android_source === 'aliyun-image' && task.progress?.current_phase === 'initializing'
          ? (task.progress?.phase_description || '正在校验并解包阿里云镜像…')
          : taskPhaseLabel(task.progress?.current_phase || task.progress?.phase)}
      </p>
    </div>
  );
}

function ActionsCell({ task, onCancel, onDelete, onJoinCase, onResume, onPause }) {
  const status = task.status?.toLowerCase();
  const finished = ['completed', 'failed', 'cancelled', 'interrupted', 'paused'].includes(status);
  // resumable comes from the backend (it checks the stage ledger + evidence
  // presence); fall back to status alone so an older server still shows the
  // action for interrupted tasks.
  const canResume = (task.resumable ?? ['failed', 'cancelled', 'interrupted', 'paused'].includes(status)) &&
    ['failed', 'cancelled', 'interrupted', 'paused'].includes(status);
  return (
    <div className="flex items-center space-x-1 text-xs font-medium">
      {status === 'running' && (
        <>
          <button onClick={() => onCancel(task.id)} className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300">
            取消
          </button>
          {onPause && !task.pause_requested && (
            <button
              onClick={() => onPause(task.id)}
              className="text-sky-600 hover:text-sky-800 dark:text-sky-400 ml-2"
              title="当前阶段结束后暂停，之后可从此处继续"
            >
              暂停
            </button>
          )}
        </>
      )}
      {canResume && onResume && (
        <button
          onClick={() => onResume(task.id)}
          className="text-amber-700 hover:text-amber-900 dark:text-amber-400 dark:hover:text-amber-300"
          title={task.resume_stage
            ? `从「${taskPhaseLabel(task.resume_stage)}」继续，已完成阶段直接跳过`
            : '从上次完成的阶段继续，已完成阶段直接跳过'}
        >
          ▶ 继续分析
        </button>
      )}
      {status === 'completed' && (
        <>
          <Link to={`/timeline?task_id=${task.id}`} className="text-primary-600 hover:underline">时间线</Link>
          <Link to={`/files?task_id=${task.id}`} className="text-green-600 hover:underline ml-1">文件</Link>
          <Link to={`/reports/task/${task.id}`} className="text-teal-600 hover:underline ml-1">报告</Link>
          {onJoinCase && (
            <button onClick={() => onJoinCase(task.id)} className="text-indigo-600 hover:underline ml-1" title="将此任务加入多镜像案件">
              加入案件
            </button>
          )}
        </>
      )}
      {finished && (
        <button onClick={() => onDelete(task.id)} className="text-slate-400 hover:text-red-600 ml-2" title="删除任务">
          🗑️
        </button>
      )}
    </div>
  );
}

export default function TaskTable({ tasks, onCancel, onDelete, onJoinCase, onResume, onPause, taskCaseMap = {}, selectedTaskIds, onToggleSelect, onToggleSelectAll }) {
  const { t } = useTranslation();
  // Multi-select is opt-in: only rendered when selectedTaskIds is provided.
  const selectable = Array.isArray(selectedTaskIds) || selectedTaskIds instanceof Set;
  const isSel = (id) => selectable && (selectedTaskIds.has ? selectedTaskIds.has(id) : selectedTaskIds.includes(id));
  const completedIds = tasks.filter((t) => t.status?.toLowerCase() === 'completed').map((t) => t.id);
  const allSelected = selectable && completedIds.length > 0 && completedIds.every((id) => isSel(id));

  if (tasks.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-slate-500 dark:text-slate-400">暂无任务，请先创建分析任务。</p>
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
            {['编号', '检材路径', '状态', '优先级', '起止时间', '进度', '操作'].map((h, i) => (
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
            const isFailed = task.status?.toLowerCase() === 'failed';
            const failureLog = isFailed
              ? [
                  `[${formatDate(task.timestamps?.completed)}] [失败] ${task.message || '任务失败'}`,
                  task.error_details ? `  └─ ${task.error_details}` : null,
                ].filter(Boolean).join('\n')
              : null;
            // An interrupted/paused task is not a failure: the detail line states
            // what was preserved and how to continue, in neutral wording.
            const isResumable = ['interrupted', 'paused'].includes(task.status?.toLowerCase());
            const resumeLog = isResumable
              ? [
                  `[${formatDate(task.timestamps?.completed)}] ${forensicLabel(task.status)}`,
                  task.resume_count > 0 ? `  ├─ 已续跑 ${task.resume_count} 次` : null,
                  `  └─ 已完成的阶段产物保留在任务目录，点击"继续分析"从断点续跑`,
                ].filter(Boolean).join('\n')
              : null;
            const selected = isSel(task.id);
            return (
            <Fragment key={task.id}>
            <tr className={`hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors ${selected ? 'bg-primary-50/60 dark:bg-primary-900/20' : ''}`}>
              {selectable && (
                <td className="px-4 py-4 whitespace-nowrap">
                  <input
                    type="checkbox"
                    disabled={!isCompleted}
                    checked={selected}
                    onChange={() => onToggleSelect && onToggleSelect(task.id)}
                    className="h-4 w-4 text-primary-600 rounded disabled:opacity-30"
                    title={isCompleted ? '勾选后可组建案件或关联离线报告' : '仅已完成任务可选'}
                  />
                </td>
              )}
              <td className="px-4 py-4 whitespace-nowrap text-[10px] font-mono text-slate-500 dark:text-slate-400">
                {task.id?.substring(0, 8)}
              </td>
              <td className="px-4 py-4 text-sm text-slate-900 dark:text-white truncate max-w-[200px]" title={task.image_path}>
                <div className="truncate">{task.metadata?.source_label || task.image_path}</div>
                {task.android_source === 'aliyun-image' && <span className="mt-1 block text-[10px] text-indigo-600"
                  title={task.metadata?.aliyun_prepared === 'true' ? `原包 SHA-256：${task.metadata.preflight_source_sha256}；RAW SHA-256：${task.metadata.aliyun_raw_sha256}` : '任务将校验并解包 RAW 后进入 Linux 分析'}>
                  {task.metadata?.aliyun_prepared === 'true' ? '阿里云镜像 · RAW 已校验' : '阿里云镜像 · 待解包校验'}
                </span>}
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
                {task.metadata?.source_verification === 'UNVERIFIED_SOURCE' &&
                  <span className="block mt-1 text-[10px] font-semibold text-amber-700 dark:text-amber-400" title="未经过 Android 镜像完整哈希及文件系统预检">来源未经预检验证</span>}
                {task.metadata?.android_coverage_status === 'COMPLETED_WITH_LOCKED_USERDATA' &&
                  <span className="block mt-1 text-[10px] font-semibold text-orange-700 dark:text-orange-400">用户数据加密锁定</span>}
                {task.metadata?.android_coverage_status === 'SUPER_NORMALIZED_NO_USERDATA' &&
                  <span className="block mt-1 text-[10px] font-semibold text-violet-700 dark:text-violet-400">已规范化，未含用户数据分区</span>}
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <PriorityBadge priority={task.priority} />
              </td>
              <td className="px-4 py-4 whitespace-nowrap leading-tight">
                <div className="flex flex-col space-y-1">
                  <div className="flex items-center text-[10px] text-slate-400">
                    <span className="w-24 uppercase shrink-0">开始：</span>
                    <span className="text-slate-600 dark:text-slate-300 font-medium">{formatDate(task.timestamps?.created)}</span>
                  </div>
                  <div className="flex items-center text-[10px] text-slate-400">
                    {/* 被服务重启中断的任务，完成时间只是中断时刻，以"中断于"语义展示 */}
                    <span className="w-24 uppercase shrink-0">
                      {task.interrupted_by_restart ? t('task.interruptedAt') : '结束：'}
                    </span>
                    <span className="text-slate-600 dark:text-slate-300 font-medium">{formatDate(task.interrupted_by_restart ? task.timestamps?.interrupted : ['COMPLETED','FAILED','CANCELLED'].includes(String(task.status).toUpperCase()) ? task.timestamps?.completed : null)}</span>
                  </div>
                </div>
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <ProgressCell task={task} />
              </td>
              <td className="px-4 py-4 whitespace-nowrap">
                <ActionsCell task={task} onCancel={onCancel} onDelete={onDelete}
                             onJoinCase={onJoinCase} onResume={onResume} onPause={onPause} />
              </td>
            </tr>
            {failureLog && (
              <tr className="bg-rose-50/60 dark:bg-rose-950/20 hover:bg-rose-50/60">
                <td colSpan={(selectable ? 1 : 0) + 7} className="px-4 py-2">
                  <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap break-all text-rose-700 dark:text-rose-300">
{failureLog}
                  </pre>
                </td>
              </tr>
            )}
            {resumeLog && (
              <tr className="bg-amber-50/60 dark:bg-amber-950/20 hover:bg-amber-50/60">
                <td colSpan={(selectable ? 1 : 0) + 7} className="px-4 py-2">
                  <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap break-all text-amber-800 dark:text-amber-300">
{resumeLog}
                  </pre>
                </td>
              </tr>
            )}
            </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
