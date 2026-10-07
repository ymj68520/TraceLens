import { useEffect, useState } from 'react';
import { pythonApi } from '../../services/api';

/** Existing file page's inline source details; never a new navigation/page. */
export default function RaidTaskOrigin({ taskId, enabled }) {
  const [source, setSource] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    setSource(null); setError('');
    if (!enabled || !taskId) return undefined;
    let alive = true;
    pythonApi.get(`/api/evidence-intake/tasks/${encodeURIComponent(taskId)}/raid-source`)
      .then((result) => { if (alive) setSource(result.source); })
      .catch(() => { if (alive) setError('RAID 来源详情暂不可用'); });
    return () => { alive = false; };
  }, [taskId, enabled]);
  if (!enabled) return null;
  return <details className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-800">
    <summary className="cursor-pointer font-medium text-slate-700 dark:text-slate-200">RAID 镜像来源</summary>
    {error ? <p className="mt-2 text-red-600">{error}</p> : source ? <dl className="mt-3 space-y-1 text-slate-600 dark:text-slate-300">
      <div>镜像：{source.label}</div><div>重组状态：{source.integrity_status}</div>
      <div>成员：{source.member_count} · 机器重组，内容未人工核验</div>
      <div className="break-all font-mono text-xs">来源清单 SHA-256：{source.manifest_sha256}</div>
      <div className="break-all font-mono text-xs">逻辑镜像 SHA-256：{source.image_sha256}</div>
      <div className="space-y-1 border-t border-slate-100 pt-2 dark:border-slate-700">
        {(source.members || []).map(member => <div key={member.relative_source} className="break-all text-xs">
          <span>{member.relative_source}</span><span className="block font-mono text-slate-400">SHA-256：{member.sha256}</span>
        </div>)}
      </div>
    </dl> : <p className="mt-2 text-slate-500">加载来源详情…</p>}
  </details>;
}
