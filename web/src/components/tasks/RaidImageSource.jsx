/** RAID selection is a field in the existing task form, not a new page. */
import { useEffect, useState } from 'react';
import Button from '../common/Button';
import { pythonApi } from '../../services/api';

const BASE = '/api/evidence-intake/raid';
const errorText = (error) => error?.data?.detail || error?.message || 'RAID 镜像准备失败';

export default function RaidImageSource({ onSource, disabled = false }) {
  const [groups, setGroups] = useState([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selected, setSelected] = useState([]);
  const [job, setJob] = useState(null);
  const [candidate, setCandidate] = useState('');
  const [partial, setPartial] = useState(false);
  const [error, setError] = useState('');
  const busy = job && ['queued', 'running'].includes(job.status);

  useEffect(() => {
    let alive = true;
    pythonApi.get(`${BASE}/candidates`).then((data) => {
      if (alive) setGroups(data.groups || []);
    }).catch((err) => { if (alive) setError(errorText(err)); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!job?.id || !busy) return undefined;
    let alive = true;
    const timer = setInterval(() => {
      pythonApi.get(`${BASE}/jobs/${job.id}`).then((response) => {
        if (!alive) return;
        const next = response.job;
        setJob(next);
        if (next.status === 'awaiting_confirmation') setCandidate(next.inference?.status === 'UNIQUE_STRUCTURAL_CANDIDATE'
          ? next.inference?.candidates?.[0]?.candidate_id || '' : '');
        if (next.status === 'ready') onSource(next.task_source);
        if (next.status === 'failed') setError(next.error_code || next.message);
      }).catch((err) => { if (alive) setError(errorText(err)); });
    }, 1000);
    return () => { alive = false; clearInterval(timer); };
  }, [job?.id, busy, onSource]);

  const reset = () => { setJob(null); setCandidate(''); setError(''); onSource(null); };
  const start = async () => {
    setError(''); onSource(null);
    try { setJob((await pythonApi.post(`${BASE}/jobs`, { member_ids: selected })).job); }
    catch (err) { setError(errorText(err)); }
  };
  const confirm = async () => {
    setError('');
    try { setJob((await pythonApi.post(`${BASE}/jobs/${job.id}/prepare`, {
      candidate_id: candidate, allow_partial: partial,
    })).job); }
    catch (err) { setError(errorText(err)); }
  };

  return (
    <div className="space-y-3" data-testid="raid-image-source">
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
        成员镜像目录
        <select className="mt-1 w-full rounded-lg border-slate-300 dark:bg-slate-700" value={groupIndex}
          disabled={disabled || busy} onChange={(event) => { setGroupIndex(Number(event.target.value)); setSelected([]); reset(); }}>
          {groups.map((group, index) => <option key={group.name} value={index}>{group.name}</option>)}
        </select>
      </label>
      <div className="max-h-40 overflow-auto rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        {!groups.length && <p className="text-sm text-slate-500">暂无已配置的 RAID 成员镜像。</p>}
        {(groups[groupIndex]?.files || []).map((file) => (
          <label key={file.id} className="flex items-center gap-2 py-1 text-sm text-slate-700 dark:text-slate-300">
            <input type="checkbox" checked={selected.includes(file.id)} disabled={disabled || busy}
              onChange={(event) => { reset(); setSelected((values) => event.target.checked ? [...values, file.id] : values.filter((id) => id !== file.id)); }} />
            <span className="truncate">{file.name}</span>
            <span className="ml-auto whitespace-nowrap text-xs text-slate-400">{(file.size / 1024**2).toFixed(1)} MB</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" disabled={disabled || busy || selected.length < 2} onClick={start}>识别成员布局</Button>
        <span className="text-xs text-slate-500">已选 {selected.length} 个成员，无需手动排列。</span>
      </div>
      {job?.status === 'awaiting_confirmation' && (
        <div className="space-y-2">
          <select aria-label="RAID 布局候选" value={candidate} onChange={(event) => setCandidate(event.target.value)}
            className="w-full rounded-lg border-slate-300 dark:bg-slate-700">
            <option value="">请选择已核对的布局候选</option>
            {(job.inference?.candidates || []).map((item) => <option key={item.candidate_id} value={item.candidate_id}>
              RAID{item.plan.level} · 条带 {item.plan.chunk_size / 1024} KB · 布局 {item.plan.layout}
            </option>)}
          </select>
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <input type="checkbox" checked={partial} onChange={(event) => setPartial(event.target.checked)} />
            允许奇偶异常时只读诊断（需管理员，保留 PARTIAL 状态）
          </label>
          <Button type="button" size="sm" onClick={confirm} disabled={!candidate ||
            !['UNIQUE_STRUCTURAL_CANDIDATE', 'AMBIGUOUS'].includes(job.inference?.status)}>确认并准备系统镜像</Button>
          <p className="text-xs text-slate-500">结构候选不等于内容已核验；准备完成后按普通镜像任务分析。</p>
        </div>
      )}
      {job && <p role="status" className="text-sm text-slate-600 dark:text-slate-300">
        {job.message || job.status}{job.integrity_status ? ` · ${job.integrity_status}` : ''}
      </p>}
      {busy && <button type="button" className="text-xs text-slate-500 underline" onClick={async () => {
        try { setJob((await pythonApi.post(`${BASE}/jobs/${job.id}/cancel`)).job); }
        catch (err) { setError(errorText(err)); }
      }}>取消镜像准备</button>}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
