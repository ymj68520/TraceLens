import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getGraphSourceFile } from '../services/graphitiService';

export default function GraphSourceFile() {
  const [params] = useSearchParams();
  const taskId = params.get('task_id');
  const evidenceKey = params.get('evidence_key');
  const relationshipId = params.get('relationship_id');
  const [source, setSource] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!taskId || !evidenceKey) { setSource(null); return undefined; }
    let active = true;
    setSource(null);
    setError(null);
    setLoading(true);
    getGraphSourceFile(taskId, evidenceKey).then((response) => {
      if (active) setSource(response.source);
    }).catch((err) => {
      if (active) setError(err?.data?.detail || err?.message || '读取失败');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [taskId, evidenceKey]);

  const back = `/knowledge-graph?task_id=${encodeURIComponent(taskId || '')}${relationshipId ? `&relationship_id=${encodeURIComponent(relationshipId)}` : ''}`;
  const preview = source?.original_preview;
  return <main className="mx-auto max-w-5xl space-y-5 p-5" data-testid="graph-source-file-page">
    <Link to={back} className="text-sm font-semibold text-primary-600 hover:underline">← 返回知识图谱关系</Link>
    <div className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
      <h1 className="text-xl font-bold text-slate-900 dark:text-white">任务文件证据</h1>
      <p className="mt-2 break-all font-mono text-sm text-slate-600 dark:text-slate-300">{source?.file_path || evidenceKey || '未指定文件'}</p>
      {source?.evidence_key && <p className="mt-1 break-all font-mono text-xs text-slate-400">{source.evidence_key}</p>}
      {loading && <p role="status" className="mt-4 text-sm text-slate-500">正在读取任务文件…</p>}
      {error && <p role="alert" className="mt-4 text-sm text-rose-600">{error}</p>}
    </div>
    {source && <>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="text-base font-semibold">真实提取副本 · 只读预览</h2>
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">提取副本不等于原始镜像。{source.source_image_available ? '原始镜像路径当前可访问，但本页未重新比对。' : '原始镜像路径当前不可访问，不能据此确认镜像完整性。'}</p>
        {!preview?.available ? <p className="mt-4 text-sm text-slate-500">{preview?.reason || '没有已提取文件副本。'}</p> : <>
          <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            <div>副本大小：{preview.file_size?.toLocaleString()} 字节</div>
            <div>数据库记录大小：{preview.recorded_size?.toLocaleString() ?? '未知'} 字节</div>
            {preview.copy_sha256 && <div className="break-all sm:col-span-2">副本 SHA-256：<span className="font-mono">{preview.copy_sha256}</span></div>}
            {preview.recorded_md5_matches_copy === true && <div className="text-emerald-700">副本与数据库 MD5 一致</div>}
            {preview.recorded_md5_matches_copy === false && <div className="text-rose-700">副本与数据库 MD5 不一致</div>}
          </dl>
          {preview.kind === 'text' ? <pre className="mt-4 max-h-[65vh] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-slate-900 p-4 text-sm text-white" data-testid="source-file-preview">{preview.text}</pre> : <>
            <p className="mt-4 text-sm text-slate-500">二进制文件：仅显示前段真实字节和可打印字符串，不对文件格式作推断。</p>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-900 p-4 font-mono text-xs text-white" data-testid="source-file-preview">{preview.hex}</pre>
            {!!preview.printable_strings?.length && <div className="mt-4">
              <h3 className="text-sm font-semibold">可打印字符串</h3>
              <ul className="mt-2 max-h-64 space-y-1 overflow-auto rounded-xl bg-slate-50 p-3 font-mono text-xs dark:bg-slate-900">
                {preview.printable_strings.map((value, index) => <li key={`${index}:${value}`} className="break-all">{value}</li>)}
              </ul>
            </div>}
          </>}
          {preview.preview_truncated && <p className="mt-2 text-xs text-slate-500">文件较大，本页仅展示前 16 KiB。</p>}
        </>}
      </section>
      {source.snapshot && <section className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="text-base font-semibold">初次分析快照（机器分析，非原始字节）</h2>
        <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700 dark:text-slate-200">{source.snapshot.initial_description || source.snapshot.initial_summary || '快照未保存描述。'}</p>
      </section>}
    </>}
  </main>;
}
