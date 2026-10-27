import { forensicLabel } from '../../utils/forensicLabels';
export default function IngestionQualityPanel({ job, onRetry, retrying = false }) {
  if (!job) return null;
  const quality = job.quality;
  const count = value => value ?? '未记录';
  return <section aria-label="图谱摄取质量" className="mt-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700">
    <p>执行状态：{forensicLabel(job.status)} · 质量：{quality?.label || '尚未评估'}</p>
    <p className="mt-1">成功 {count(quality?.successful)} / 总数 {count(quality?.total)} · 失败 {count(quality?.failed)} · 未处理 {count(quality?.unprocessed)}</p>
    {(quality?.reasons || []).map((text, i) => <p key={i} className="mt-1 text-xs text-amber-700 dark:text-amber-300">{text}</p>)}
    <p className="mt-1 text-xs text-slate-500">{quality?.scope || '当前运行记录'} · 运行编号 {job.job_id}</p>
    {quality?.retryable && onRetry && <button type="button" onClick={onRetry} disabled={retrying} className="mt-2 text-blue-700 disabled:opacity-50">{retrying ? '正在重试…' : '重试未完成摄取'}</button>}
  </section>;
}
