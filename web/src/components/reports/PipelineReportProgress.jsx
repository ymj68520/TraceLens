import { useEffect, useRef, useState } from 'react';
import { getPipelineReportStatus, getReportGeneration } from '../../services/reportGenerationService';
import { forensicError } from '../../utils/forensicLabels';
import { fetchTaskById } from '../../services/taskService';

export default function PipelineReportProgress({ taskId, onReportAvailable, onOpenReport,
  loadTail = getPipelineReportStatus, loadGeneration = getReportGeneration, loadTask = fetchTaskById, pollIntervalMs = 5000 }) {
  const [view, setView] = useState(null);
  const callbacks = useRef({ onReportAvailable, onOpenReport });
  callbacks.current = { onReportAvailable, onOpenReport };
  useEffect(() => {
    let active = true, timer, notified = null;
    setView(null);
    const poll = async () => {
      let terminal = false;
      try {
        const tail = await loadTail(taskId);
        if (!active) return;
        let generation = null;
        if (tail?.generation_id) generation = await loadGeneration(taskId, tail.generation_id);
        if (!active) return;
        const state = generation?.status || tail?.state;
        const reportId = generation?.report_id || tail?.report_id;
        setView({ state, reportId, error: generation?.error_message || tail?.error_message,
          quality: generation?.quality?.label, generationId: tail?.generation_id });
        if (state === 'completed' && reportId && notified !== reportId) {
          notified = reportId; callbacks.current.onReportAvailable?.(reportId);
        }
        terminal = state === 'completed' || state === 'failed';
      } catch (error) {
        if (!active) return;
        const status = error?.status || error?.response?.status;
        if (status === 404) {
          try {
            const task = await loadTask(taskId);
            if (!active) return;
            if (['failed', 'cancelled', 'interrupted'].includes(task?.status))
              setView({ state: 'upstream_failed', error: task.message });
            else if (['running', 'pending', 'paused'].includes(task?.status))
              setView({ state: task.status === 'paused' ? 'paused' : 'waiting' });
            else setView(null);
          } catch { if (active) setView(null); }
        } else setView({ state: 'unavailable' });
      }
      if (active) timer = setTimeout(poll, terminal ? Math.max(pollIntervalMs, 15000) : pollIntervalMs);
    };
    if (taskId) void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [taskId, loadTail, loadGeneration, loadTask, pollIntervalMs]);
  if (!view?.state || view.state === 'idle') return null;
  const failed = view.state === 'failed' || view.state === 'upstream_failed';
  const done = view.state === 'completed';
  const label = view.state === 'upstream_failed' ? '报告前置处理未完成' : failed ? '本轮报告生成未通过' : done ? '本轮报告已生成'
    : view.state === 'unavailable' ? '暂时无法读取报告生成状态'
      : view.state === 'paused' ? '任务已暂停，报告等待继续处理'
        : view.state === 'waiting' ? '报告等待材料分析和图谱摄取完成'
      : view.generationId ? '正在研判、写作与审校报告' : '正在准备与冻结报告材料';
  return <div role={failed ? 'alert' : 'status'} aria-label="自动报告生成状态"
    className={`rounded-lg border p-4 text-sm ${failed ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-blue-200 bg-blue-50 text-blue-900'}`}>
    <p className="font-medium">{label}</p>
    {failed && <p className="mt-1">{forensicError(view.error, '请核对本轮来源与报告校验原因，当前没有可交付的新报告。')}</p>}
    {view.quality && <p className="mt-1">质量状态：{view.quality}</p>}
    {done && view.reportId && <button type="button" className="mt-2 underline"
      onClick={() => callbacks.current.onOpenReport?.(view.reportId)}>查看本轮报告</button>}
  </div>;
}
